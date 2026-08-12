import random
from urllib.parse import urljoin
import requests
from django.conf import settings
from django.utils import timezone
from .models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostCampaignModel
from ai.models import AIModel
import json
import traceback

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
            task_id = response['task_id']
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

            print("BOT:", bot)
            print("PROXY:", bot.proxy)
            print("PROXY TYPE:", type(bot.proxy))
            print("FIREFOX JSON:", bot.firefox_json_path)
            print("FIREFOX TYPE:", type(bot.firefox_json_path))

            firefox_json = json.loads(bot.firefox_json_path)

            print("FIREFOX LOADED:", firefox_json)
            print("FIREFOX LOADED TYPE:", type(firefox_json))

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
                                                        "proxy_port": bot.proxy['port']}}).json(),
                task_id = response['task_id']
                task_ids.append(task_id)

            campaign.task_ids = task_ids
            campaign.status = "pending"
            campaign.save()

        except Exception as e:
            traceback.print_exc()
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
        for comment in comments:
            user_url = comment['user_url']
            comment_url = comment['link']
            comment_text = comment['text']
            action = random.choice(actions)
            bot = random.choice(bots)
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
                    if post.campaign.comment_prompt:
                        prompt = f"""
                        {post.campaign.comment_prompt}
                        فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
                        کامنت:
                        {comment_text}
                        """
                    else:
                        prompt = f"""
                        یک جواب برای این کامنت تولید کن
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
