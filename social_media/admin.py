from django.contrib import admin
from .models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostCampaignModel, PostMediaModel


class PostMediaInline(admin.TabularInline):
    model = PostMediaModel
    extra = 1


@admin.register(ActionModel)
class ActionAdmin(admin.ModelAdmin):
    list_filter = ["status", "action", "campaign"]
    list_display = ["action", "bot", "send_date"]
    inlines = [PostMediaInline]


@admin.register(PostCampaignModel)
class PostAdmin(admin.ModelAdmin):
    list_filter = ["status", "campaign"]


@admin.register(CampaignSocialMediaModel)
class CampaignAdmin(admin.ModelAdmin):
    list_filter = ["status", "social_media", "working"]


@admin.register(ProfileModel)
class ProfileAdmin(admin.ModelAdmin):
    list_filter = ["status", "social_media"]
