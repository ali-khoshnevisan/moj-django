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
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = getattr(settings, "INSTAGRAM_SESSION_REFRESH_INTERVAL", timedelta(hours=3))
MAX_PROFILES_PER_RUN = getattr(settings, "INSTAGRAM_SESSION_REFRESH_BATCH", 10)
PAGE_TIMEOUT_MS = 60_000


def _lock_path(profile_path):
    name = os.path.basename(profile_path.rstrip("/").rstrip("\\"))
    return os.path.join(
        getattr(settings, "PROFILE_LOCK_DIR", "/tmp"),
        f"ffprofile-{name}.lock",
    )


def _extract_session_id(cookies):
    for c in cookies:
        if c.get("name") == "sessionid" and c.get("domain") in (".instagram.com", "instagram.com"):
            return c.get("value")
    return None


def _dump_instagrapi_session(session_id, proxy_username, port):
    """Build an instagrapi session from a fresh sessionid, return JSON string."""
    cl = Client()
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
            # Cookies are gone/expired — this one genuinely needs a human to
            # log in again through the edit browser. Flag it so the dashboard
            # and the user can see it.
            return False, "no sessionid cookie — manual re-login required"

        session_json = _dump_instagrapi_session(session_id, proxy_username, port)
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
    try:
        profile = ProfileModel.objects.get(pk=profile_id, social_media="instagram")
    except ProfileModel.DoesNotExist:
        return {"ok": False, "msg": "profile not found"}

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


def action_process():
    print("START ACTION SOCIAL MEDIA TASKS MANAGER")
    requested_tasks = ActionModel.objects.filter(status='requested', working=True)
    for task in requested_tasks:
        try:
            if task.send_date > timezone.now():
                print(f"now is {timezone.now()}message will sent after {task.send_date}")
                continue

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
                                           "data": {"url": task.url,
                                                    "text": task.text,
                                                    "medias": medias,
                                                    "username": task.bot.username,
                                                    "proxy_host": task.bot.proxy['host'],
                                                    "proxy_username": task.bot.proxy['username'],
                                                    "proxy_pass": task.bot.proxy['password'],
                                                    "proxy_port": task.bot.proxy['port'],
                                                    "firefox_json_path": json.loads(task.bot.firefox_json_path)}}).json()
            task_id = response['task_id']
            task.task_id = task_id
            task.status = 'pending'
            task.save()

        except Exception as e:
            print(e)

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
                            social_media=post.campaign.social_media,
                            url=comment_url,
                            bot=bot,
                            action=action,
                            campaign=post.campaign
                        )
                    except Exception as e:
                        print(e)
                elif action == "follow":
                    try:
                        ActionModel.objects.create(
                            social_media=post.campaign.social_media,
                            url=user_url,
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
                                "social_media": post.campaign.social_media,
                                "url": comment_url,
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
                                    "social_media": post.campaign.social_media,
                                    "url": comment_url,
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
