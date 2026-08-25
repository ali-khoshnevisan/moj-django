import os
from datetime import timedelta
from django.utils import timezone
from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings

def upload_to_profile(instance, filename):
    return os.path.join(f'{instance.social_media}_files', 'profile', str(instance.pk), filename)


def upload_to_post(instance, filename):
    return os.path.join('post', f'{instance.action.pk}', 'media', str(instance.pk), filename)


social_media_choices = (
    ('instagram', 'instagram'),
    ('twitter', 'twitter')
)

profile_status_choices = (
    ('requested', 'requested'),
    ("checking-profile", "checking-profile"),
    ("profile-is-not-login", "profile-is-not-login"),
    ("grab-profile", "grab-profile"),
    ('pending', 'pending'),
    ('added', 'added'),
)

default_max_action_choices = 5


class ProfileModel(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='social_profiles')
    social_media = models.CharField(max_length=10, choices=social_media_choices)
    firefox_profile_path = models.CharField(max_length=1000, unique=True, blank=True, null=True)
    firefox_json_path = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=100, default='requested', choices=profile_status_choices)
    username = models.CharField(max_length=40, blank=True, null=True)
    url = models.URLField()
    followers = models.CharField(max_length=20, blank=True, null=True)
    followings = models.CharField(max_length=20, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    posts_count = models.IntegerField(default=0)
    profile_image = models.URLField(blank=True, null=True)
    image = models.FileField(blank=True, null=True, upload_to=upload_to_profile)
    last_update = models.DateTimeField(auto_now_add=True)
    next_eligible_at = models.DateTimeField(default=timezone.now)
    pause_time = models.IntegerField(default=4)
    session_updated_at = models.DateTimeField(blank=True, null=True)
    session_refresh_error = models.CharField(max_length=500, blank=True, null=True)
    max_actions_per_hour = models.JSONField(blank=True, null=True)
    task_id = models.UUIDField(blank=True, null=True)
    proxy = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ['-last_update']
        constraints = [
            models.UniqueConstraint(
                fields=['social_media', 'username'],
                name='unique_username_per_social_media'
            )
        ]

    # def clean(self):
    #     actions_options = set(action_choices[self.social_media])
    #     if not isinstance(self.max_actions_per_hour, dict):
    #         raise ValidationError("max_actions_per_hour must be a dictionary")
    #     if set(self.max_actions_per_hour.keys()) != actions_options:
    #         raise ValidationError(f"max_actions_per_hour keys must be {actions_options}")
    #
    #     for action in self.max_actions_per_hour.keys():
    #         if not isinstance(self.max_actions_per_hour[action], int):
    #             raise ValidationError(
    #                 "the value of every action in max_actions_per_hour must be a number")
    #
    #         if not self.max_actions_per_hour[action]:
    #             self.max_actions_per_hour[action] = default_max_action_choices
    #
    # def save(self, *args, **kwargs):
    #     self.full_clean()
    #     super().save(*args, **kwargs)


action_choices = {
    'instagram': ['like', 'comment', 'follow', 'post', 'direct'],
    'twitter': ['like', 'comment', 'follow', 'post', 'direct'],
}

action_status_choices = (
    ("requested", "requested"),
    ("pending", "pending"),
    ("failed", "failed"),
    ("success", "success"),
)


class ActionModel(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='social_actions')
    social_media = models.CharField(max_length=10, choices=social_media_choices)
    url = models.URLField(blank=True, null=True)
    last_update = models.DateTimeField(auto_now=True)
    action = models.CharField(max_length=20)
    status = models.CharField(max_length=10, default="requested", choices=action_status_choices)
    bot = models.ForeignKey(ProfileModel, on_delete=models.CASCADE, blank=False, null=True)
    text = models.TextField(blank=True, null=True)
    send_date = models.DateTimeField(default=timezone.now)
    result = models.JSONField(blank=True, null=True)
    task_id = models.UUIDField(blank=True, null=True)
    working = models.BooleanField(default=True, editable=True, db_index=True)
    campaign = models.ForeignKey("CampaignSocialMediaModel", on_delete=models.SET_NULL, blank=True, null=True,
                                 related_name="actions_objects")

    class Meta:
        ordering = ['-last_update']

    def clean(self):
        allowed_actions = action_choices.get(self.social_media, [])
        if self.action not in allowed_actions:
            raise ValidationError({
                'action': f"{self.action} is not allowed for {self.social_media}"
            })

        # bot.max_actions_per_hour is nullable — without this guard, any
        # bot that never had it configured crashes every single save() here.
        if not self.bot.max_actions_per_hour:
            return

        limit = self.bot.max_actions_per_hour.get(self.action)
        if not limit:
            return
        interval = timedelta(days=1) / limit

        qs = self.__class__.objects.filter(
            bot=self.bot,
            action=self.action,
            send_date__gte=timezone.now() - timedelta(days=1)
        ).order_by('-send_date')

        if qs.count() < limit:
            return

        last_action = qs[limit - 1]
        next_allowed_time = last_action.send_date + timedelta(days=1)

        if self.send_date < next_allowed_time:
            self.send_date = next_allowed_time

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    # @property
    # def post_type(self):
    #     if self.action != "post":
    #         return None
    #     medias = self.medias
    #     media_types = []
    #     for media in medias:
    #         media_types.append(media.media_types)
    #
    #     if "video" in media_types:
    #         return "post_video"
    #     elif "photo" in media_types:
    #         if len(media_types) == 1:
    #             return "post_single_photo"
    #         else:
    #             return "post_multiple_photo"


media_type_choices = (
    ("photo", "photo"),
    ("video", "video"),
    ("cover", "cover"),
)


class PostMediaModel(models.Model):
    action = models.ForeignKey(ActionModel, on_delete=models.CASCADE, related_name='medias')
    media = models.FileField(upload_to=upload_to_post)
    media_type = models.CharField(max_length=20, choices=media_type_choices)


class CampaignSocialMediaModel(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='social_campaigns')
    social_media = models.CharField(max_length=10, choices=social_media_choices)
    urls = models.JSONField(default=list)
    actions = models.JSONField(default=list)
    bots = models.ManyToManyField(ProfileModel)
    posts = models.JSONField(default=list, blank=True, null=True)
    campaign_description = models.TextField(blank=True, null=True)
    comment_prompt = models.TextField(blank=True, null=True)
    direct_prompt = models.TextField(blank=True, null=True)
    working = models.BooleanField(default=True, db_index=True)
    status = models.CharField(max_length=10, choices=action_status_choices, default="requested")
    task_ids = models.JSONField(default=list, blank=True, null=True)

    def clean(self):
        if not isinstance(self.actions, list):
            raise ValidationError("actions must be an array")
        if not self.actions:
            raise ValidationError("actions can not be empty")
        for action in self.actions:
            if action not in action_choices[self.social_media]:
                raise ValidationError(f"action {action} is not valid for {self.social_media}")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


post_status_choices = (
    ("requested", "requested"),
    ("pending", "pending"),
    ("failed", "failed"),
    ("success", "success"),
    ("created", "created"),
)


class PostCampaignModel(models.Model):
    campaign = models.ForeignKey(CampaignSocialMediaModel, on_delete=models.SET_NULL, blank=False, null=True,
                                 related_name='posts_objects')
    url = models.URLField()
    comments = models.JSONField(default=list, blank=True, null=True)
    status = models.CharField(max_length=10, choices=post_status_choices, default="requested")
    working = models.BooleanField(default=True, editable=True, db_index=True)
    task_id = models.UUIDField(blank=True, null=True)

    def clean(self):
        if not self.comments:
            self.comments = []
            return

        cleaned_comments = []

        for comment in self.comments:
            if not comment.get('link'):
                continue

            if comment.get("username"):
                if self.campaign.social_media == "instagram":
                    comment["user_url"] = (
                        f"https://www.instagram.com/{comment['username']}/"
                    )
                    cleaned_comments.append(comment)

        self.comments = cleaned_comments

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)