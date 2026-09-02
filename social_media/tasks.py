import random
from urllib.parse import urljoin
import requests
from django.conf import settings
from django.utils import timezone
from .models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostCampaignModel
from ai.models import AIModel
import json
import os
import logging
from datetime import timedelta
from celery import shared_task
from django.db.models import Q
from filelock import FileLock, Timeout
from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired, LoginRequired, BadPassword,
    FeedbackRequired, AccountSuspended, PleaseWaitFewMinutes,
    ClientError,
)
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = getattr(settings, "INSTAGRAM_SESSION_REFRESH_INTERVAL", timedelta(hours=3))
MAX_PROFILES_PER_RUN = getattr(settings, "INSTAGRAM_SESSION_REFRESH_BATCH", 10)
PAGE_TIMEOUT_MS = 60_000


def _lock_path(profile_path):
    # FileLock creates the lock FILE but not its parent DIRECTORY. Without
    # this makedirs, a missing dir raises FileNotFoundError from acquire() —
    # which is not a Timeout, so it escapes _refresh_one and kills the batch.
    lock_dir = getattr(settings, "PROFILE_LOCK_DIR", "/tmp")
    os.makedirs(lock_dir, exist_ok=True)
    name = os.path.basename(profile_path.rstrip("/").rstrip("\\"))
    return os.path.join(lock_dir, f"ffprofile-{name}.lock")


def _extract_session_id(cookies):
    for c in cookies:
        if c.get("name") == "sessionid" and c.get("domain") in (".instagram.com", "instagram.com"):
            return c.get("value")
    return None


def _dump_instagrapi_session(session_id, proxy_username, port, existing_settings=None):
    """
    Build an instagrapi session from a fresh sessionid, return JSON string.

    `existing_settings` is the profile's CURRENT firefox_json_path content.
    Reusing it is essential, not an optimisation: a bare Client() invents new
    device UUIDs, device_settings and user_agent on every call, so each
    refresh would look to Instagram like the account moved to a brand-new
    phone — which is exactly what triggers ChallengeRequired. set_settings()
    restores the stored device identity so the account stays consistent.
    """
    cl = Client()

    if existing_settings:
        try:
            cl.set_settings(json.loads(existing_settings))
        except Exception as e:  # noqa: BLE001
            # Corrupt/empty stored settings shouldn't block the refresh, but
            # it does mean a new device identity — worth knowing about.
            logger.warning("could not reuse stored settings (new device id will be generated): %s", e)

    proxy_url = (
        f"{proxy_username}:{settings.PROXY_PASSWORD}"
        f"@{settings.PROXY_HOST}:{port}"
    )
    cl.set_proxy(proxy_url)
    cl.login_by_sessionid(session_id)

    tmp_path = os.path.join(
        getattr(settings, "PROFILE_LOCK_DIR", "/tmp"),
        f"session-refresh-{os.getpid()}.json",
    )
    try:
        cl.dump_settings(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _mark_not_login(profile, msg):
    ProfileModel.objects.filter(pk=profile.pk).update(
        status="profile-is-not-login",
        session_refresh_error=msg,
    )
    return False, msg


def _build_authenticated_client(profile):
    if not profile.firefox_json_path:
        return None, "no session stored for this profile — needs initial login"

    try:
        settings_dict = json.loads(profile.firefox_json_path)
    except (json.JSONDecodeError, TypeError) as e:
        return None, f"stored session is not valid JSON: {e}"

    if isinstance(settings_dict, str):
        logger.warning(
            "profile %s has double-encoded firefox_json_path — decoding again "
            "and repairing the stored value",
            profile.pk,
        )
        try:
            settings_dict = json.loads(settings_dict)
        except (json.JSONDecodeError, TypeError) as e:
            return None, f"stored session is double-encoded AND the inner value is not valid JSON: {e}"

        if isinstance(settings_dict, dict):
            # Repair it now so this profile doesn't hit this path again on
            # its next action.
            ProfileModel.objects.filter(pk=profile.pk).update(
                firefox_json_path=json.dumps(settings_dict)
            )

    if not settings_dict or not isinstance(settings_dict, dict):
        return None, "stored session is empty or not a JSON object"

    proxy = profile.proxy or {}
    proxy_username = proxy.get("username")
    proxy_port = proxy.get("port")
    if not proxy_username or not proxy_port:
        return None, "profile has no proxy username/port"

    cl = Client()
    cl.set_settings(settings_dict)

    proxy_url = (
        f"{proxy_username}:{settings.PROXY_PASSWORD}"
        f"@{settings.PROXY_HOST}:{proxy_port}"
    )
    cl.set_proxy(proxy_url)

    if not cl.user_id:
        return None, "stored session has no logged-in user — needs re-login"

    return cl, None


def _normalize_post_url(url):
    from urllib.parse import urlparse

    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]

    for prefix in ("p", "reel", "tv"):
        if prefix in parts:
            idx = parts.index(prefix)
            if idx + 1 < len(parts):
                shortcode = parts[idx + 1]
                return f"{parsed.scheme}://{parsed.netloc}/{prefix}/{shortcode}/"

    return url


def _extract_comment_id(url):
    from urllib.parse import urlparse

    parts = [p for p in urlparse(url).path.split("/") if p]
    if "c" in parts:
        idx = parts.index("c")
        if idx + 1 < len(parts) and parts[idx + 1].isdigit():
            return parts[idx + 1]
    return None


def _resolve_media_target(client, url):
    """like/comment target: a POST url. Normalized first (see
    _normalize_post_url) in case it's actually a comment permalink."""
    return client.media_pk_from_url(_normalize_post_url(url))


def _resolve_user_target(client, url):
    """follow/direct target: a PROFILE url. instagrapi's
    user_id_from_username only strips '@'/whitespace, it does NOT parse a
    full URL — so the username has to be pulled out of the path here."""
    from urllib.parse import urlparse

    path = urlparse(url).path.strip("/")
    if not path:
        raise ValueError(f"could not extract a username from url: {url!r}")

    username = path.split("/")[0]
    # Guards against a post URL (/p/<code>/) or other non-profile path
    # accidentally reaching here and being read as a "username".
    if username in ("p", "reel", "reels", "stories", "tv"):
        raise ValueError(
            f"url looks like a post/reel/story url, not a profile url: {url!r}"
        )

    return client.user_id_from_username(username)


def perform_instagram_action(profile, action, url, text=None):
    if action not in ("like", "comment", "follow", "direct"):
        return "failed", f"action '{action}' is not supported by direct execution yet"

    client, err = _build_authenticated_client(profile)
    if client is None:
        return "not_login", err

    try:
        if action == "like":
            comment_id = _extract_comment_id(url)
            if comment_id:
                client.comment_like(comment_id)
                return "success", f"liked comment {comment_id}"
            media_id = _resolve_media_target(client, url)
            client.media_like(media_id)
            return "success", f"liked media {media_id}"

        elif action == "comment":
            if not text:
                return "failed", "comment action requires text"

            reply_to = _extract_comment_id(url)
            media_id = _resolve_media_target(client, url)

            if reply_to:
                client.media_comment(media_id, text, replied_to_comment_id=reply_to)
                return "success", f"replied to comment {reply_to} on media {media_id}"

            client.media_comment(media_id, text)
            return "success", f"commented on media {media_id}"

        elif action == "follow":
            user_id = _resolve_user_target(client, url)
            client.user_follow(user_id)
            return "success", f"followed user {user_id}"

        elif action == "direct":
            if not text:
                return "failed", "direct action requires text"
            user_id = _resolve_user_target(client, url)
            client.direct_send(text, user_ids=[int(user_id)])
            return "success", f"sent direct to user {user_id}"

    except ValueError as e:
        # our own target-resolution errors (bad/unparseable url)
        return "failed", str(e)[:500]

    except TypeError as e:
        raw_response = getattr(client, "last_json", "<no last_json available>")
        logger.warning(
            "malformed API response for %s on profile %s: %s | last_json=%r",
            action, profile.pk, e, raw_response,
        )
        return "failed", f"malformed response from instagram/proxy: {str(raw_response)[:300]}"

    except AccountSuspended as e:
        # More severe than a normal challenge — the account itself is
        # suspended, not just needing re-verification. Still routed to
        # profile-is-not-login since that's the only "needs attention"
        # status this model has, but the message makes the real cause clear.
        return "not_login", f"account suspended: {e}"[:500]

    except ChallengeRequired as e:
        return "not_login", f"challenge/checkpoint required: {e}"[:500]

    except (LoginRequired, BadPassword) as e:
        return "not_login", f"session rejected: {e}"[:500]

    except FeedbackRequired as e:
        # THIS is Instagram's rate-limit/spam-block signal — distinct from
        # a dead session. The account is still logged in; it's being
        # throttled for acting too fast/too much. Worth its own message
        # even though it maps to the same profile-is-not-login status,
        # since "your credentials are fine, you were just too aggressive"
        # is a very different thing to act on than "log back in".
        return "not_login", f"rate-limited by Instagram (feedback_required): {e}"[:500]

    except PleaseWaitFewMinutes as e:
        # Transient throttle, not an auth problem — do NOT mark the
        # profile not-login for this one, just fail this action so it can
        # be retried on the normal schedule.
        return "failed", f"instagram asked to wait a few minutes: {e}"[:500]

    except ClientError as e:
        # Catch-all for any other instagrapi/API-level failure we didn't
        # anticipate above. Treated as a normal action failure, not an
        # auth failure, since we don't actually know it's a login problem.
        return "failed", f"instagrapi error: {e}"[:500]

    except Exception as e:  # noqa: BLE001
        logger.exception("unexpected error performing %s for profile %s", action, profile.pk)
        return "failed", f"unexpected error: {e}"[:500]


def _refresh_one(profile):
    profile_path = profile.firefox_profile_path
    if not profile_path or not os.path.isdir(profile_path):
        return False, "firefox profile directory missing on disk"

    proxy = profile.proxy or {}
    proxy_username = proxy.get("username")
    port = proxy.get("port")
    if not proxy_username or not port:
        return False, "profile has no proxy username/port"

    lock = FileLock(_lock_path(profile_path), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        # Someone (probably main_ws, user editing live) holds the profile.
        # Skipping is correct — we'll catch it on the next beat.
        return False, "profile busy (in use elsewhere), skipped"

    try:
        with sync_playwright() as pw:
            browser = pw.firefox.launch_persistent_context(
                user_data_dir=profile_path,
                headless=True,  # ← the whole point: invisible to the user
                proxy={
                    "server": f"http://{settings.PROXY_HOST}:{port}",
                    "username": proxy_username,
                    "password": settings.PROXY_PASSWORD,
                },
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                firefox_user_prefs={
                    "intl.accept_languages": "en-US,en",
                    "intl.locale.requested": "en-US",
                    "javascript.use_us_english_locale": True,
                    "media.peerconnection.enabled": False,
                    "geo.enabled": False,
                    "toolkit.telemetry.enabled": False,
                    "network.predictor.enabled": False,
                },
            )
            try:
                page = browser.new_page()
                page.set_viewport_size({"width": 1280, "height": 720})
                page.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                )
                page.goto(
                    "https://www.instagram.com/",
                    wait_until="domcontentloaded",
                    timeout=PAGE_TIMEOUT_MS,
                )
                # Give Instagram a moment to set/rotate cookies.
                page.wait_for_timeout(5000)

                cookies = browser.cookies()
                session_id = _extract_session_id(cookies)
            finally:
                browser.close()

        if not session_id:
            return _mark_not_login(
                profile, "no sessionid cookie — manual re-login required"
            )

        try:
            session_json = _dump_instagrapi_session(
                session_id, proxy_username, port,
                existing_settings=profile.firefox_json_path,
            )
        except ChallengeRequired:
            return _mark_not_login(
                profile,
                "manual re-login required: Instagram challenge/checkpoint on this account",
            )
        except (LoginRequired, BadPassword):
            return _mark_not_login(
                profile,
                "manual re-login required: credentials/session rejected",
            )

        if not session_json:
            return False, "instagrapi produced an empty session"

        profile.firefox_json_path = session_json
        profile.session_updated_at = timezone.now()
        profile.session_refresh_error = None
        if profile.status == "profile-is-not-login":
            profile.status = "added"
        profile.save(update_fields=[
            "firefox_json_path", "session_updated_at",
            "session_refresh_error", "status",
        ])
        return True, "session refreshed"

    except Exception as exc:  # noqa: BLE001 - we want any failure recorded, not raised
        logger.exception("session refresh failed for profile %s", profile.pk)
        return False, str(exc)[:500]
    finally:
        lock.release()


@shared_task(name="social_media.refresh_instagram_sessions")
def refresh_instagram_sessions():
    """
    Periodic entrypoint (Celery beat, every 3h). Picks up Instagram profiles
    whose session is stale or never generated, and refreshes them one at a
    time. Sequential on purpose: each refresh spawns a real Firefox, and
    running ten at once will flatten the server.
    """
    cutoff = timezone.now() - REFRESH_INTERVAL

    due = (
        ProfileModel.objects
        .filter(social_media="instagram")
        .filter(status="added")
        .exclude(firefox_profile_path__isnull=True)
        .exclude(firefox_profile_path="")
        # stale = never refreshed, or last refresh older than the cutoff
        .filter(Q(session_updated_at__isnull=True) | Q(session_updated_at__lt=cutoff))
        .order_by("session_updated_at")[:MAX_PROFILES_PER_RUN]
    )

    results = {"refreshed": 0, "skipped": 0, "failed": 0}
    for profile in due:
        ok, msg = _refresh_one(profile)
        if ok:
            results["refreshed"] += 1
        elif "busy" in msg:
            results["skipped"] += 1
        else:
            results["failed"] += 1
            ProfileModel.objects.filter(pk=profile.pk).update(
                session_refresh_error=msg,
                # surfaces in the panel so the user knows to re-login manually
                status="profile-is-not-login" if "manual re-login" in msg else profile.status,
            )
        logger.info("profile %s: %s", profile.pk, msg)

    logger.info("refresh_instagram_sessions finished: %s", results)
    return results


@shared_task(name="social_media.refresh_single_instagram_session")
def refresh_single_instagram_session(profile_id):
    """
    Manual/on-demand refresh for one profile — handy to wire to a
    'Refresh session' button in the panel without waiting for the next beat.
    """
    try:
        profile = ProfileModel.objects.get(
            pk=profile_id, social_media="instagram", status="added"
        )
    except ProfileModel.DoesNotExist:
        return {
            "ok": False,
            "msg": "profile not found, or its status is not 'added' "
                   "(a profile flagged profile-is-not-login must be logged "
                   "in again through the edit browser first)",
        }

    ok, msg = _refresh_one(profile)
    if not ok:
        ProfileModel.objects.filter(pk=profile.pk).update(session_refresh_error=msg)
    return {"ok": ok, "msg": msg}


def profile_process():
    print("START PROFILE SOCIAL MEDIA TASKS MANAGER")
    requested_profiles = ProfileModel.objects.filter(status='requested')
    # for profile in requested_profiles:
    #     try:
    #         response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
    #                                  json={"worker_type": f"{profile.social_media}-check-profile",
    #                                        "data": {"url": profile.url}}).json()
    #         task_id = response['task_id']
    #         profile.task_id = task_id
    #         profile.status = 'checking-profile'
    #         profile.save()
    #
    #     except Exception as e:
    #         print(e)

    # grab_profiles = ProfileModel.objects.filter(status='grab-profile')
    for profile in requested_profiles:
        try:
            response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                     json={"worker_type": f"{profile.social_media}-profile",
                                           "data": {"url": profile.url,
                                                    "firefox_json_path": json.loads(profile.firefox_json_path),
                                                    "proxy_host": profile.proxy['host'],
                                                    "proxy_username": profile.proxy['username'],
                                                    "proxy_pass": profile.proxy['password'],
                                                    "proxy_port": profile.proxy['port'],
                                                    "username": profile.username}}).json()
            task_id = response['task_id']
            profile.task_id = task_id
            profile.status = 'pending'
            profile.save()

        except Exception as e:
            print(e)

    # added_profiles = ProfileModel.objects.filter(status='added', task_id__isnull=True,
    #                                              last_update__lte=timezone.now() -
    #                                                               settings.SOCIAL_MEDIA_PROFILE_CRAWLER_UPDATE_TIME)
    # for profile in added_profiles:
    #     try:
    #         response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
    #                                  json={"worker_type": f"{profile.social_media}-profile",
    #                                        "data": {"url": profile.url}}).json()
    #         task_id = response['task_id']
    #         profile.task_id = task_id
    #         profile.save()

        # except Exception as e:
        #     print(e)

    print("FINISH PROFILE SOCIAL MEDIA TASKS MANAGER")

def update_bot_next_eligible(profile):
    pause_minutes = random.randint(1, 59)
    ProfileModel.objects.filter(pk=profile.pk).update(
        next_eligible_at=timezone.now() + timedelta(hours=profile.pause_time, minutes=pause_minutes),
    )

def action_process():
    print("START ACTION SOCIAL MEDIA TASKS MANAGER")
    requested_tasks = ActionModel.objects.filter(status='requested', working=True)
    for task in requested_tasks:
        try:
            if task.bot.status == "profile-is-not-login":
                continue

            if task.send_date > timezone.now():
                print(f"now is {timezone.now()}message will sent after {task.send_date}")
                continue

            if task.bot.next_eligible_at > timezone.now():
                continue

            if task.action == "post":
                medias = []
                for media in task.medias.all():
                    if media.media.url.startswith("http"):
                        media_url = media.media.url
                    else:
                        media_url = urljoin("http://46.225.112.201:6688", media.media.url)
                    medias.append((media_url, media.media_type))
                    print('post medias: ', medias)
                response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                         json={"worker_type": f"{task.social_media}-{task.action}",
                                               "data": {"text": task.text,
                                                        "medias": medias,
                                                        "username": task.bot.username,
                                                        "proxy_host": task.bot.proxy['host'],
                                                        "proxy_username": task.bot.proxy['username'],
                                                        "proxy_pass": task.bot.proxy['password'],
                                                        "proxy_port": task.bot.proxy['port'],
                                                        "firefox_json_path": json.loads(
                                                            task.bot.firefox_json_path)}}).json()
                task_id = response['task_id']
                task.task_id = task_id
                task.status = 'pending'
                update_bot_next_eligible(task.bot)
                task.save()
                continue

            task.status = 'pending'
            task.save(update_fields=["status"])

            outcome, detail = perform_instagram_action(
                profile=task.bot,
                action=task.action,
                url=task.url,
                text=task.text,
            )
            print(f"[action_process] task {task.pk} outcome={outcome}: {detail}")

            if outcome == "success":
                task.status = 'success'
                task.result = {"detail": detail}
                task.task_id = None
                task.save(update_fields=["status", "result", "task_id"])
                update_bot_next_eligible(task.bot)

            elif outcome == "not_login":
                task.status = 'failed'
                task.result = {"detail": detail}
                task.task_id = None
                task.save(update_fields=["status", "result", "task_id"])
                ProfileModel.objects.filter(pk=task.bot_id).update(
                    status="profile-is-not-login",
                    session_refresh_error=detail,
                )

            else:  # "failed"
                task.status = 'failed'
                task.result = {"detail": detail}
                task.task_id = None
                task.save(update_fields=["status", "result", "task_id"])

        except Exception as e:
            print(f"[action_process] ERROR on task {task.pk}: {e}")
            # Task was already flipped to 'pending' above before this
            # exception — without this, it would be stuck at 'pending'
            # forever with no completion status, the exact same silent-
            # stuck-state bug fixed earlier in telegram_worker_task.
            try:
                ActionModel.objects.filter(pk=task.pk).update(
                    status='failed',
                    result={"detail": f"unhandled error: {e}"[:500]},
                    task_id=None,
                )
            except Exception as inner_e:
                print(f"[action_process] could not even record failure for task {task.pk}: {inner_e}")

    print("FINISH ACTION SOCIAL MEDIA TASKS MANAGER")


def crawl_campaign():
    print("START CAMPAIGN SOCIAL MEDIA TASKS MANAGER")
    requested_campaigns = CampaignSocialMediaModel.objects.filter(status='requested', working=True)
    for campaign in requested_campaigns:
        try:
            bot = campaign.bots.first()

            if not bot:
                raise Exception(f"Campaign {campaign.id} has no bot")

            task_ids = []
            for url in campaign.urls:
                response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                         json={"worker_type": f"{campaign.social_media}-profile",
                                               "data": {"url": url,
                                                        "firefox_json_path": json.loads(bot.firefox_json_path),
                                                        "username": bot.username,
                                                        "proxy_host": bot.proxy['host'],
                                                        "proxy_username": bot.proxy['username'],
                                                        "proxy_pass": bot.proxy['password'],
                                                        "proxy_port": bot.proxy['port']}}).json()
                task_id = response['task_id']
                task_ids.append(task_id)

            campaign.task_ids = task_ids
            campaign.status = "pending"
            campaign.save()

        except Exception as e:
            print(e)

    pending_campaigns = CampaignSocialMediaModel.objects.filter(status='pending', working=True)
    for campaign in pending_campaigns:
        if not campaign.task_ids:
            for post in campaign.posts:
                try:
                    PostCampaignModel.objects.create(campaign=campaign, url=post)
                except Exception as e:
                    print(e)
            campaign.status = "success"
            campaign.save()

    print("FINISH CAMPAIGN SOCIAL MEDIA TASKS MANAGER")


def crawl_post_campaign():
    print("START CAMPAIGN POST SOCIAL MEDIA TASKS MANAGER")
    requested_posts = PostCampaignModel.objects.filter(status='requested', working=True)
    for post in requested_posts:
        try:
            response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                     json={"worker_type": f"{post.campaign.social_media}-comments",
                                           "data": {"url": post.url}}).json()
            task_id = response['task_id']
            post.task_id = task_id
            post.status = "pending"
            post.save()

        except Exception as e:
            print(e)

    print("FINISH CAMPAIGN POST SOCIAL MEDIA TASKS MANAGER")


def create_actions():
    print("START CAMPAIGN CREATE ACTION SOCIAL MEDIA TASKS MANAGER")
    posts = PostCampaignModel.objects.filter(status="success", working=True)
    for post in posts:
        bots = post.campaign.bots.all()
        actions = list(post.campaign.actions)

        comments = post.comments

        if not comments:
            continue

        first_comment_text = comments[0].get('text', '')

        for index, comment in enumerate(comments):
            user_url = comment.get('user_url', '')
            comment_url = comment.get('link', '')
            comment_text = comment.get('text', '')
            action = random.choice(actions)
            for bot in bots:
                if action == "like":
                    try:
                        ActionModel.objects.create(
                            user=post.campaign.user,
                            social_media=post.campaign.social_media,
                            url=comment_url,
                            target_account_url=user_url,
                            bot=bot,
                            action=action,
                            campaign=post.campaign
                        )
                    except Exception as e:
                        print(e)
                elif action == "follow":
                    try:
                        ActionModel.objects.create(
                            user=post.campaign.user,
                            social_media=post.campaign.social_media,
                            url=user_url,
                            target_account_url=user_url,
                            bot=bot,
                            action=action,
                            campaign=post.campaign
                        )
                    except Exception as e:
                        print(e)
                elif action == "comment":
                    try:
                        caption_context = ""
                        if index > 0 and first_comment_text:
                            caption_context = f"""این کامنت برای این پست گذاشته شده و باید بهش یک جواب مرتبط بدی.
                            کپشن پست:
                            {first_comment_text}
                            """
                        if post.campaign.comment_prompt:
                            prompt = f"""
                            {post.campaign.comment_prompt}
                            {caption_context}
                            فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
                            کامنت:
                            {comment_text}
                            """
                        else:
                            prompt = f"""
                            یک جواب برای این کامنت تولید کن
                            {caption_context}
                            فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
                            کامنت:
                            {comment_text}
                            """
                        AIModel.objects.create(
                            ai_type="chatgpt",
                            request=prompt,
                            comment_details={
                                "user": post.campaign.user_id,
                                "social_media": post.campaign.social_media,
                                "url": comment_url,
                                "target_account_url": user_url,
                                "bot": bot.id,
                                "action": action,
                                "campaign": post.campaign.id
                            })
                    except Exception as e:
                        print(e)

                elif action == "direct":
                    try:
                        if post.campaign.direct_prompt:
                            prompt = f"""
                            {post.campaign.direct_prompt}
                            فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
                            """

                            AIModel.objects.create(
                                ai_type="chatgpt",
                                request=prompt,
                                comment_details={
                                    "user": post.campaign.user_id,
                                    "social_media": post.campaign.social_media,
                                    "url": comment_url,
                                    "target_account_url": user_url,
                                    "bot": bot.id,
                                    "action": action,
                                    "campaign": post.campaign.id
                                })
                    except Exception as e:
                        print(e)
                else:
                    continue

        post.status = "created"
        post.save()

    print("FINISH CAMPAIGN CREATE ACTION SOCIAL MEDIA TASKS MANAGER")