from django.db import models
from social_media.models import ActionModel
from crawler.models import PostModel

ai_type_choices = (
    ('grok', 'grok'),
    ('chatgpt', 'chatgpt')
)

status_choices = (
    ('requested', 'requested'),
    ('pending', 'pending'),
    ('failed', 'failed'),
    ('success', 'success')
)


class AIModel(models.Model):
    ai_type = models.CharField(max_length=10, choices=ai_type_choices)
    request = models.TextField()
    response = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=status_choices, default='requested')
    comment_details = models.JSONField(default=dict, blank=True, null=True)
    post_details = models.JSONField(default=dict, blank=True, null=True)
    task_id = models.UUIDField(blank=True, null=True)
    last_update = models.DateTimeField(auto_now=True)
    failed_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-last_update']

    def comment_answer(self):
        if not (self.comment_details and self.response):
            print("creating comment action failed")
            print("comment details:", self.comment_details)
            print("response:", self.response)
            return

        ActionModel.objects.create(
            user_id=self.comment_details.get("user"),
            text=self.response,
            url=self.comment_details.get("url"),
            target_account_url=self.comment_details.get("target_account_url"),
            target_post=self.comment_details.get("target_post"),
            bot_id=self.comment_details.get("bot"),
            campaign_id=self.comment_details.get("campaign"),
            social_media=self.comment_details.get("social_media"),
            action=self.comment_details.get("action")
        )

    def post_answer(self):
        print('post answer', self.response)
        if not (self.post_details and self.response):
            print("creating post answer failed")
            print("post details:", self.post_details)
            print("response:", self.response)
            return


        PostModel.objects.filter(pk=self.post_details.get("post_pk")).update(
            ai_response=self.response,
        )
