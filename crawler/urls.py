from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'crawler'

router = DefaultRouter()
router.register(r'account', views.AccountViewSet)
router.register(r'post', views.PostViewSet)
router.register(r'web-single-post', views.WebSinglePostView)
router.register(r'telegram-bot', views.TelegramBotView)
router.register(r'telegram-send-post', views.TelegramSendPostView)

urlpatterns = [
    path('', include(router.urls), name='router'),
]
