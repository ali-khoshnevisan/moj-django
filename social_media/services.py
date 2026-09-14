from .models import ActionModel


def create_action(**kwargs):
    bot = kwargs["bot"]
    target_account_url = kwargs.get("target_account_url")
    campaign = kwargs.get("campaign")

    is_campaign_url = (
        target_account_url
        and campaign
        and target_account_url in (campaign.urls or [])
    )

    if not is_campaign_url:
        exists = ActionModel.objects.filter(
            bot=bot,
            target_account_url=target_account_url
        ).exists()

        if exists:
            return None

    return ActionModel.objects.create(**kwargs)