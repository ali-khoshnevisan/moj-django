from urllib.parse import urljoin
from datetime import timedelta
import requests
from django.conf import settings
from django.utils import timezone
from .models import AccountModel, PostModel, WebSinglePostModel, TelegramSendPost
from ai.models import AIModel


def _crawler(platform, pstatus, timer):
    print(f"START CRAWLER TASKS MANAGER ON PLATFORM {platform.upper()} WITH STATUS {pstatus.upper()}")
    accounts = AccountModel.objects.filter(status=pstatus, platform=platform, task_id__isnull=True,
                                           last_update__lte=timezone.now() - timer)
    for account in accounts:
        try:
            response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                     json={"worker_type": f"{account.platform}-crawler",
                                           "data": {"url": account.url, "config": account.config}}).json()
            task_id = response['task_id']
            account.task_id = task_id
            account.save()

        except Exception as e:
            print(e)
    print(f"FINISH CRAWLER TASKS MANAGER ON PLATFORM {platform.upper()} WITH STATUS {pstatus.upper()}")


def post_crawler():
    requested_posts = PostModel.objects.filter(status="requested", task_id__isnull=True)
    for post in requested_posts:
        response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                 json={"worker_type": f"{post.account.platform}-crawler-single-post",
                                       "data": {"url": post.url, "config": post.account.config}}).json()
        task_id = response['task_id']
        post.task_id = task_id
        post.save()

    created_posts = PostModel.objects.filter(status="created")
    for post in created_posts:
        if post.account.ai_prompt:
            prompt = f"""
                        {post.account.ai_prompt}
                        فقط جوابو بگو چون میخوام مستقیم کپی ش کنم و بفرستم برای طرف
                        متن:
                        {post.text}
                    """
            AIModel.objects.create(
                ai_type="chatgpt",
                request=prompt,
                post_details={"post_pk": post.pk})

        post.status = "ai-generated"
        post.save()


def crawler():
    _crawler("web", "requested", timedelta(seconds=0))
    _crawler("web", "enable", settings.WEB_CRAWLER_UPDATE_TIME)
    _crawler("telegram", "requested", timedelta(seconds=0))
    _crawler("telegram", "enable", settings.TELEGRAM_CRAWLER_UPDATE_TIME)
    post_crawler()


def crawl_web_single_post():
    print("START WEB SINGLE POST CRAWLER TASKS MANAGER")
    requested_posts = WebSinglePostModel.objects.filter(status='requested')
    for post in requested_posts:
        try:
            response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                     json={"worker_type": f"web-crawler-single-post-test",
                                           "data": {"url": post.url, "config": post.config}}).json()
            task_id = response['task_id']
            post.task_id = task_id
            post.status = 'pending'
            post.save()

        except Exception as e:
            print(e)

    print("FINISH WEB SINGLE POST CRAWLER TASKS MANAGER")


def telegram_bot():
    print("START TELEGRAM SEND POST TASKS MANAGER")
    posts = TelegramSendPost.objects.filter(status='requested')
    for post in posts:
        post.send()

    print("FINISH TELEGRAM SEND POST TASKS MANAGER")
