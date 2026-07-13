from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CampaignSocialMediaModel, PostCampaignModel, ActionModel


@receiver(post_save, sender=CampaignSocialMediaModel)
def sync_campaign_working(sender, instance, **kwargs):
    ActionModel.objects.filter(
        campaign=instance
    ).update(
        working=instance.working
    )

    PostCampaignModel.objects.filter(
        campaign=instance
    ).update(
        working=instance.working
    )
