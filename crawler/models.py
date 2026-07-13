from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from asgiref.sync import async_to_sync
from telegram import Bot

platform_choices = (
    ('telegram', 'telegram'),
    ('web', 'web'),
)

account_status_choices = (
    ('enable', 'enable'),
    ('disable', 'disable'),
    ('requested', 'requested')
)

default_web_config = {
    "url_cfg": "",
    "title_cfg": "",
    "description_cfg": "",
    "remove_cfg": "",
    "image_cfg": ""
}

valid_web_configs = set(default_web_config.keys())


class AccountModel(models.Model):
    url = models.URLField(unique=True)
    platform = models.CharField(max_length=10, choices=platform_choices)
    config = models.JSONField(blank=True, null=True)
    status = models.CharField(max_length=20, default="requested", choices=account_status_choices)
    ai_prompt = models.TextField(blank=True, null=True)
    last_update = models.DateTimeField(auto_now_add=True)
    task_id = models.UUIDField(blank=True, null=True)

    class Meta:
        ordering = ['-last_update']

    def clean(self):
        if self.platform == "web":
            if not self.config:
                raise ValidationError("Web Platform must have a config.")
            if not isinstance(self.config, dict):
                raise ValidationError("Web Platform must have a valid config.")
            keys = set(self.config.keys())
            if keys != valid_web_configs:
                raise ValidationError("invalid config, arguments must be:", tuple(valid_web_configs))

            for key in self.config:
                if not self.config[key]:
                    self.config[key] = default_web_config[key]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


post_status_choices = (
    ("requested", "requested"),
    ("trash", "trash"),
    ("created", "created"),
    ("ai-generated", "ai-generated"),
)


def upload_post_media_path(instance, filename):
    return f'crawler/post_{instance.pk}/{filename}'


class PostModel(models.Model):
    url = models.URLField(unique=True)
    account = models.ForeignKey(AccountModel, on_delete=models.CASCADE)
    title = models.TextField(blank=True, null=True)
    text = models.TextField()
    media = models.URLField(blank=True, null=True)
    media_file = models.FileField(upload_to=upload_post_media_path, blank=True, null=True)
    comments = models.JSONField(blank=True, null=True)
    ai_response = models.TextField(blank=True, null=True)
    task_id = models.UUIDField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=100, choices=post_status_choices)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.account.ai_prompt:
            self.ai_response = "Processing for generating Ai response, please wait..."
        super().save(*args, **kwargs)


web_single_post_status_choices = (
    ("requested", "requested"),
    ("pending", "pending"),
    ("failed", "failed"),
    ("success", "success"),
)


class WebSinglePostModel(models.Model):
    url = models.URLField()
    config = models.JSONField()
    title = models.TextField(blank=True, null=True)
    text = models.TextField(blank=True, null=True)
    media = models.URLField(blank=True, null=True)
    task_id = models.UUIDField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=web_single_post_status_choices, default='requested')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        if not self.config:
            raise ValidationError("Web Platform must have a config.")
        if not isinstance(self.config, dict):
            raise ValidationError("Web Platform must have a valid config.")
        keys = set(self.config.keys())
        if keys != valid_web_configs:
            raise ValidationError("invalid config, arguments must be:", tuple(valid_web_configs))

        for key in self.config:
            if not self.config[key]:
                self.config[key] = default_web_config[key]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


telegram_model_status_choices = (
    ("enable", "enable"),
    ("disable", "disable"),
    ("check-bot", "check-bot")
)


class TelegramModel(models.Model):
    token = models.CharField(max_length=100, unique=True)
    channel = models.CharField(max_length=50)
    text_header = models.TextField(blank=True, null=True)
    text_footer = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=telegram_model_status_choices)


telegram_post_status_choices = (
    ('requested', 'requested'),
    ('sent', 'sent'),
    ('failed', 'failed')
)


async def send_bot(token, channel, text=None, media=None, media_type=None):
    bot = Bot(token=token)

    if not media:
        await bot.send_message(
            chat_id=channel,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return

    if media_type == "photo":
        await bot.send_photo(
            chat_id=channel,
            photo=media,
            caption=text,
            parse_mode="HTML"
        )

    elif media_type == "video":
        await bot.send_video(
            chat_id=channel,
            video=media,
            caption=text,
            parse_mode="HTML"
        )

    elif media_type == "document":
        await bot.send_document(
            chat_id=channel,
            document=media,
            caption=text,
            parse_mode="HTML"
        )

    elif media_type == "audio":
        await bot.send_audio(
            chat_id=channel,
            audio=media,
            caption=text,
            parse_mode="HTML"
        )

    else:
        raise ValueError(f"unsupported media type: {media_type}")


def telegram_media_path(instance, filename):
    return f'accounts/post_{instance.pk}/{filename}'


telegram_media_choices = (
    ("photo", "photo"),
    ("video", "video"),
    ("audio", "audio"),
    ("document", "document")
)


class TelegramSendPost(models.Model):
    bot = models.ForeignKey(TelegramModel, on_delete=models.CASCADE)
    text = models.TextField()
    media = models.FileField(upload_to=telegram_media_path, blank=True, null=True)
    media_type = models.CharField(max_length=10, choices=telegram_media_choices, blank=True, null=True)
    send_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=telegram_post_status_choices, default='requested')
    error_message = models.CharField(max_length=1000, blank=True, null=True)

    def send(self):
        if self.send_date.astimezone() > timezone.now():
            print(f"now is {timezone.now()}message will sent after {self.send_date.astimezone()}")
            return

        text = self.text
        if self.bot.text_header:
            text = self.bot.text_header + "\n" + text

        if self.bot.text_footer:
            text = text + "\n" + self.bot.text_footer

        try:
            async_to_sync(send_bot)(self.bot.token, self.bot.channel, text, self.media, self.media_type)
            self.status = 'sent'
        except Exception as e:
            print(e)
            self.bot.status = "check-bot"
            self.bot.save()
            self.error_message = str(e)
            self.status = "failed"

        self.save()
