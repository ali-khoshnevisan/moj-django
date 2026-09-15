from .models import ActionModel, CampaignSocialMediaModel


def create_action(**kwargs):
    bot_id = kwargs["bot_id"]
    target_account_url = kwargs.get("target_account_url")
    target_post = kwargs.get("target_post")
    campaign = kwargs.get("campaign")

    is_campaign_url = (
        target_account_url
        and campaign
        and target_account_url in (campaign.urls or [])
    )

    if not is_campaign_url:
        post_duplicate = ActionModel.objects.filter(
            bot_id=bot_id,
            target_post=target_post
        ).exists()

        account_duplicate = ActionModel.objects.filter(
            bot_id=bot_id,
            target_account_url=target_account_url
        ).exists()

        if post_duplicate and not account_duplicate:
            create_secondary_campaign(
                bot_id,
                target_account_url,
                campaign,
            )
            return None

    return ActionModel.objects.create(**kwargs)

def create_secondary_campaign(bot_id, target_account_url, campaign):
    if campaign.is_secondary:
        return

    # campaign_exists = CampaignSocialMediaModel.objects.filter(
    #     bots__id=bot_id,
    #     urls__contains=[target_account_url],
    # ).exists()

    campaigns = CampaignSocialMediaModel.objects.filter(
        bots__id=bot_id
    )

    campaign_exists = any(
        target_account_url in (campaign.urls or [])
        for campaign in campaigns
    )

    if campaign_exists:
        return

    new_campaign = CampaignSocialMediaModel.objects.create(
        user=campaign.user,
        social_media=campaign.social_media,
        urls=[target_account_url],
        actions=campaign.actions,
        comment_prompt=campaign.comment_prompt,
        direct_prompt=campaign.direct_prompt,
        is_secondary=True,
    )

    new_campaign.bots.add(bot_id)
