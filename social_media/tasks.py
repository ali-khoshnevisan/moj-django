import random
from urllib.parse import urljoin
import requests
from django.conf import settings
from django.utils import timezone
from .models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostCampaignModel
from ai.models import AIModel
from datetime import timedelta, datetime
from urllib.parse import urlparse
from .services import create_secondary_campaign
from celery import shared_task

REGISTER_PROFILE_URL = "http://91.107.232.169:7700/login"
SUBMIT_CODE_URL = "http://91.107.232.169:7700/submit-code"
REGISTER_PROFILE_TIMEOUT = 300

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
                                                    "username": profile.username}}).json()
            task_id = response['task_id']
            profile.task_id = task_id
            profile.status = 'fetching_profile'
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
        next_eligible_at=timezone.now() + timedelta(hours=1, minutes=pause_minutes),
    )

def action_process():
    print("START ACTION SOCIAL MEDIA TASKS MANAGER")
    requested_tasks = ActionModel.objects.filter(status='requested', working=True)
    # flag = 0
    for task in requested_tasks:
        try:
            if task.bot.status == "profile-is-not-login":
                continue

            # if task.send_date > timezone.now():
            #     print(f"now is {timezone.now()}message will sent after {task.send_date}")
            #     continue

            # if task.bot.next_eligible_at > timezone.now():
            #     continue

            # if task.bot.sleep_from < datetime.now().hour < task.bot.sleep_to:
            #     continue

            # if flag > 5:
            #     update_bot_next_eligible(task.bot)
            #     continue

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
                                                    "url": task.url,
                                                    "crop": task.crop,
                                                    "medias": medias,
                                                    "username": task.bot.username}}).json()
            task_id = response['task_id']
            # flag += 1
            task.task_id = task_id
            task.status = 'pending'
            task.save()

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
                                                        "username": bot.username}}).json()
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

def get_instagram_post_url(url):
    path = urlparse(url).path
    parts = path.strip("/").split("/")

    if len(parts) >= 2 and parts[0] == "p":
        return parts[1]

    return None

def select_random_comment(bot, comments, campaign):
    campaign_urls = set(campaign.urls or []) if campaign else set()

    already_actioned = set(
        ActionModel.objects.filter(bot=bot)
        .exclude(target_account_url__isnull=True)
        .exclude(target_account_url="")
        .values_list("target_account_url", flat=True)
    )

    eligible = []
    for comment in comments:
        account_url = comment.get("user_url", "")
        if account_url and campaign_urls and account_url in campaign_urls:
            eligible.append(comment)
        elif account_url not in already_actioned:
            eligible.append(comment)

    if not eligible:
        return None

    return random.choice(eligible)


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

        for bot in bots:
            selected_comment = select_random_comment(bot, comments, post.campaign)
            if selected_comment is None:
                continue

            user_url = selected_comment.get('user_url', '')
            comment_url = selected_comment.get('link', '')
            comment_text = selected_comment.get('text', '')
            post_url = get_instagram_post_url(comment_url)
            action = random.choice(actions)

            if action == "like":
                try:
                    ActionModel.objects.create(
                        user=post.campaign.user,
                        social_media=post.campaign.social_media,
                        url=comment_url,
                        target_account_url=user_url,
                        target_post=post_url,
                        bot_id=bot.id,
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
                        target_post=post_url,
                        bot_id=bot.id,
                        action=action,
                        campaign=post.campaign
                    )
                except Exception as e:
                    print(e)
            elif action == "comment":
                try:
                    caption_context = ""
                    if first_comment_text and first_comment_text != comment_text:
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
                            "target_post": post_url,
                            "bot_id": bot.id,
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
                                "url": user_url,
                                "target_account_url": user_url,
                                "target_post": post_url,
                                "bot_id": bot.id,
                                "action": action,
                                "campaign": post.campaign.id
                            })
                except Exception as e:
                    print(e)
            else:
                continue

            other_comments = [
                comment
                for comment in comments
                if comment != comments[0] and comment != selected_comment
            ]

            for comment in other_comments:
                user_url = comment.get('user_url', '')
                create_secondary_campaign(
                    bot_id=bot.id,
                    target_account_url=user_url,
                    campaign=post.campaign
                )

        post.status = "created"
        post.save()

    print("FINISH CAMPAIGN CREATE ACTION SOCIAL MEDIA TASKS MANAGER")


@shared_task(name="social_media.register_profile_with_service")
def register_profile_with_service(profile_id):
    try:
        profile = ProfileModel.objects.get(pk=profile_id)
    except ProfileModel.DoesNotExist:
        return {"ok": False, "reason": "profile no longer exists"}

    # try:
    #     delete_response = requests.post(
    #         f"http://91.107.232.169:7700/profiles/{profile.username}",
    #         timeout=REGISTER_PROFILE_TIMEOUT,
    #     )
    # except requests.RequestException as e:
    #     print(e)

    payload = {
        "username": profile.username,
        "password": profile.password,
        "totp_secret": profile.totp,
        "proxy": f"vahid2026:vihanbaba2026@127.0.0.1:{profile.proxy["port"]}",
        "sleep_from": profile.sleep_from.strftime("%H:%M"),
        "sleep_to": profile.sleep_to.strftime("%H:%M"),
    }

    try:
        response = requests.post(
            REGISTER_PROFILE_URL,
            json=payload,
            timeout=REGISTER_PROFILE_TIMEOUT,
        )
    except requests.RequestException as e:
        ProfileModel.objects.filter(pk=profile_id).update(
            status="profile-is-not-login",
            warning_flag=True
        )
        return {"ok": False, "reason": f"request failed: {e}"}

    if 200 <= response.status_code < 300:
        data = response.json()

        if data.get("needs_2fa_code") or data.get('needs_email_code') is True:
            ProfileModel.objects.filter(pk=profile_id).update(
                status="2fa_required",
                warning_flag=True,
            )
            return {
                "ok": True,
                "status_code": response.status_code,
                "needs_2fa_code": True,
            }

        ProfileModel.objects.filter(pk=profile_id).update(
            status="requested",
            warning_flag=False
        )
        return {"ok": True, "status_code": response.status_code}


    ProfileModel.objects.filter(pk=profile_id).update(
        status="profile-is-not-login",
        warning_flag=True
    )
    return {"ok": False, "status_code": response.status_code, "body": response.text[:500]}


@shared_task(name="social_media.submit_code_to_service")
def submit_code_to_service(profile_id, code):
    try:
        profile = ProfileModel.objects.get(pk=profile_id)
    except ProfileModel.DoesNotExist:
        return {"ok": False, "reason": "profile no longer exists"}

    payload = {
        "username": profile.username,
        "code": code,
    }

    try:
        response = requests.post(
            SUBMIT_CODE_URL,
            json=payload,
            timeout=REGISTER_PROFILE_TIMEOUT,
        )
    except requests.RequestException as e:
        ProfileModel.objects.filter(pk=profile_id).update(
            status="profile-is-not-login",
            warning_flag=True
        )
        return {"ok": False, "reason": f"request failed: {e}"}

    if 200 <= response.status_code < 300:
        data = response.json()

        if data.get("success") is True:
            ProfileModel.objects.filter(pk=profile_id).update(
                status="requested",
                warning_flag=False
            )
            return {
                "ok": True,
                "status_code": response.status_code,
            }
        ProfileModel.objects.filter(pk=profile_id).update(status="profile-is-not-login", warning_flag=True)
        return {"ok": True, "status_code": response.status_code}

    ProfileModel.objects.filter(pk=profile_id).update(
        status="profile-is-not-login",
        warning_flag=True
    )
    return {
        "ok": False,
        "status_code": response.status_code,
        "body": response.text[:500]
    }