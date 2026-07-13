from django.apps import AppConfig


class SocialMediaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'social_media'

    def ready(self):
        import social_media.signals
