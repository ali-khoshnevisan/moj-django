import time
from django.core.management.base import BaseCommand
from ai.tasks import ai_process
from crawler.tasks import crawler, crawl_web_single_post, telegram_bot
from social_media.tasks import action_process, profile_process, crawl_campaign, crawl_post_campaign, create_actions

tasks = [ai_process, crawler, crawl_web_single_post, telegram_bot, crawl_campaign, action_process, profile_process,
         crawl_post_campaign, create_actions]


class Command(BaseCommand):
    help = "Run Tasks"

    def handle(self, *args, **kwargs):
        while True:
            for task in tasks:
                try:
                    task()
                except Exception as e:
                    print(e)

            time.sleep(10)
