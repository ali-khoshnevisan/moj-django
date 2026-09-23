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

            if task.bot.sleep_from < datetime.now().hour < task.bot.sleep_to:
                continue

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
    comment = random.choice(comments)
    account_url = comment.get('user_url', '')
    is_campaign_url = (
        account_url
        and campaign
        and account_url in (campaign.urls or [])
    )

    if is_campaign_url:
        return comment

    account_duplicate = ActionModel.objects.filter(
        bot=bot,
        target_account_url=account_url
    ).exists()

    if account_duplicate:
        select_random_comment(bot, comments, campaign)
        return None

    return comment


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

        # for index, comment in enumerate(comments):
        #     user_url = comment.get('user_url', '')
        #     comment_url = comment.get('link', '')
        #     comment_text = comment.get('text', '')
        #     post_url = get_instagram_post_url(comment_url)
        #     action = random.choice(actions)
        #     for bot in bots:
        #         if action == "like":
        #             try:
        #                 ActionModel.objects.create(
        #                     user=post.campaign.user,
        #                     social_media=post.campaign.social_media,
        #                     url=comment_url,
        #                     target_account_url=user_url,
        #                     target_post=post_url,
        #                     bot=bot,
        #                     action=action,
        #                     campaign=post.campaign
        #                 )
        #             except Exception as e:
        #                 print(e)
        #         elif action == "follow":
        #             try:
        #                 ActionModel.objects.create(
        #                     user=post.campaign.user,
        #                     social_media=post.campaign.social_media,
        #                     url=user_url,
        #                     target_account_url=user_url,
        #                     target_post=post_url,
        #                     bot=bot,
        #                     action=action,
        #                     campaign=post.campaign
        #                 )
        #             except Exception as e:
        #                 print(e)
        #         elif action == "comment":
        #             try:
        #                 caption_context = ""
        #                 if index > 0 and first_comment_text:
        #                     caption_context = f"""این کامنت برای این پست گذاشته شده و باید بهش یک جواب مرتبط بدی.
        #                     کپشن پست:
        #                     {first_comment_text}
        #                     """
        #                 if post.campaign.comment_prompt:
        #                     prompt = f"""
        #                     {post.campaign.comment_prompt}
        #                     {caption_context}
        #                     فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
        #                     کامنت:
        #                     {comment_text}
        #                     """
        #                 else:
        #                     prompt = f"""
        #                     یک جواب برای این کامنت تولید کن
        #                     {caption_context}
        #                     فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
        #                     کامنت:
        #                     {comment_text}
        #                     """
        #                 AIModel.objects.create(
        #                     ai_type="chatgpt",
        #                     request=prompt,
        #                     comment_details={
        #                         "user": post.campaign.user_id,
        #                         "social_media": post.campaign.social_media,
        #                         "url": comment_url,
        #                         "target_account_url": user_url,
        #                         "target_post": post_url,
        #                         "bot": bot.id,
        #                         "action": action,
        #                         "campaign": post.campaign.id
        #                     })
        #             except Exception as e:
        #                 print(e)
        #
        #         elif action == "direct":
        #             try:
        #                 if post.campaign.direct_prompt:
        #                     prompt = f"""
        #                     {post.campaign.direct_prompt}
        #                     فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
        #                     """
        #
        #                     AIModel.objects.create(
        #                         ai_type="chatgpt",
        #                         request=prompt,
        #                         comment_details={
        #                             "user": post.campaign.user_id,
        #                             "social_media": post.campaign.social_media,
        #                             "url": user_url,
        #                             "target_account_url": user_url,
        #                             "target_post": post_url,
        #                             "bot": bot.id,
        #                             "action": action,
        #                             "campaign": post.campaign.id
        #                         })
        #             except Exception as e:
        #                 print(e)
        #         else:
        #             continue

        post.status = "created"
        post.save()

    print("FINISH CAMPAIGN CREATE ACTION SOCIAL MEDIA TASKS MANAGER")


@shared_task(name="social_media.register_profile_with_service")
def register_profile_with_service(profile_id):
    try:
        profile = ProfileModel.objects.get(pk=profile_id)
    except ProfileModel.DoesNotExist:
        return {"ok": False, "reason": "profile no longer exists"}

    payload = {
        "username": profile.username,
        "password": profile.password,
        "totp_secret": profile.totp,
        "proxy": f"vahid2026:vihanbaba2026@127.0.0.1:{profile.proxy["port"]}",
        "sleep_from": profile.sleep_from,
        "sleep_to": profile.sleep_to,
    }

    try:
        response = requests.post(
            REGISTER_PROFILE_URL,
            json=payload,
            timeout=REGISTER_PROFILE_TIMEOUT,
        )
    except requests.RequestException as e:
        ProfileModel.objects.filter(pk=profile_id).update(
            status="profile-is-not-login"
        )
        return {"ok": False, "reason": f"request failed: {e}"}

    if 200 <= response.status_code < 300:
        ProfileModel.objects.filter(pk=profile_id).update(status="requested")
        return {"ok": True, "status_code": response.status_code}

    ProfileModel.objects.filter(pk=profile_id).update(
        status="profile-is-not-login"
    )
    return {"ok": False, "status_code": response.status_code, "body": response.text[:500]}
