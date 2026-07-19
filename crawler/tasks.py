from urllib.parse import urljoin
import os
import uuid
import filetype
from datetime import timedelta
import requests
from django.conf import settings
from django.utils import timezone
from .models import AccountModel, PostModel, WebSinglePostModel, TelegramSendPost
from ai.models import AIModel
from django.core.files import File
from bs4 import BeautifulSoup
from celery import shared_task
import re
from requests.adapters import HTTPAdapter, Retry

REQUEST_TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TelegramScraper/1.0)"
}

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
    # _crawler("telegram", "requested", timedelta(seconds=0))
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

def make_session(proxies: dict = None, headers: dict = None) -> requests.Session:
    s = requests.Session()
    if proxies:
        s.proxies.update(proxies)
    if headers:
        s.headers.update(headers)

    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def normalize_link(link: str) -> str:
    if not link:
        return None
    link = link.strip()
    if not link.startswith("http"):
        link = "https://t.me/" + link
    if "/s/" not in link:
        username = link.rstrip("/").split("/")[-1]
        link = f"https://t.me/s/{username}"
    return link


def download_media(url: str, save_dir: str = "media"):
    os.makedirs(save_dir, exist_ok=True)

    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()

    first_chunk = next(response.iter_content(8192))

    kind = filetype.guess(first_chunk)
    ext = f".{kind.extension}" if kind else ""

    filepath = os.path.join(
        save_dir,
        f"{uuid.uuid4().hex}{ext}"
    )

    with open(filepath, "wb") as f:
        f.write(first_chunk)

        for chunk in response.iter_content(8192):
            if chunk:
                f.write(chunk)

    return os.path.abspath(filepath)


def get_last_posts(channel):
    session = make_session(
        # proxies=get_proxy(),
        headers=HEADERS)
    url = normalize_link(channel)
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    posts = soup.find_all("div", class_="tgme_widget_message", attrs={"data-post": True})
    all_posts = []

    for post_div in posts:
        data_post = post_div.get("data-post")
        if not data_post:
            continue

        text = ""
        text_div = post_div.find("div", class_="tgme_widget_message_text")
        if text_div:
            for br in text_div.find_all("br"):
                br.replace_with("\n")
            text = text_div.get_text("\n", strip=True)

        datetimes = []
        for time_tag in post_div.find_all("time"):
            if time_tag.has_attr("datetime"):
                datetimes.append(time_tag["datetime"])

        media = []

        for tag in post_div.find_all(style=True):
            style = tag.get("style", "")
            match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
            if match:
                url = match.group(1)
                if re.search(r"\.jpg$", url, re.IGNORECASE):
                    if not url.startswith("https://t.me/"):
                        media.append(url)

        for video_tag in post_div.find_all("video"):
            src = video_tag.get("src")
            if src and not src.startswith("https://t.me/"):
                media.append(src)

        for doc in post_div.find_all("a", href=True):
            cls = " ".join(doc.get("class", []))
            href = doc["href"]
            if ("document" in cls) or ("/file/" in href) or re.search(r"t\.me/.+/\d+", href):
                if href not in media and not href.startswith("https://t.me/"):
                    media.append(href)

        all_posts.append({
            "url": f"https://t.me/{data_post}",
            "text": text,
            "media": media[0] if media else None,
            "media_path": download_media(media[0]) if media else None
        })

    return all_posts

@shared_task
def telegram_worker_task(account_id, url):
    try:
        extracted_posts = get_last_posts(url)

        account = AccountModel.objects.get(id=account_id)

        for post_data in extracted_posts:
            new_post = PostModel.objects.create(
                account=account,
                url=post_data.get("url"),
                text=post_data.get("text"),
                media=post_data.get("media"),
                status="created"
            )

            media_path = post_data.get("media_path")
            if media_path and os.path.exists(media_path):
                with open(media_path, 'rb') as f:
                    file_name = os.path.basename(media_path)
                    new_post.media_file.save(file_name, File(f))
                os.remove(media_path)

        account.status = "enable"
        account.task_id = None
        account.save()

        return f"Successfully crawled {len(extracted_posts)} posts for account {account_id}"

    except Exception as e:
        print(f"Error in telegram_worker_task: {e}")
        try:
            account = AccountModel.objects.get(id=account_id)
            account.task_id = None
            account.save()
        except AccountModel.DoesNotExist:
            pass
        return str(e)