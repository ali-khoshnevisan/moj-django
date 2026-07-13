from django.contrib import admin
from .models import AccountModel, PostModel, WebSinglePostModel, TelegramModel, TelegramSendPost

admin.site.register(WebSinglePostModel)
admin.site.register(TelegramModel)


@admin.register(AccountModel)
class AccountAdmin(admin.ModelAdmin):
    list_filter = ["status"]
    list_display = ["url", "platform", "status", "last_update"]


@admin.register(PostModel)
class PostAdmin(admin.ModelAdmin):
    list_filter = ['account__platform', 'account', 'status']


@admin.register(TelegramSendPost)
class TelegramSendPostAdmin(admin.ModelAdmin):
    list_filter = ['bot']
