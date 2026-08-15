from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'crawler'

router = DefaultRouter()
router.register(r'account', views.AccountViewSet, basename='account')
router.register(r'post', views.PostViewSet, basename='post')
router.register(r'web-single-post', views.WebSinglePostView, basename='web-single-post')
router.register(r'telegram-bot', views.TelegramBotView, basename='telegram-bot')
router.register(r'telegram-send-post', views.TelegramSendPostView, basename='telegram-send-post')

urlpatterns = [
    path('', include(router.urls), name='router'),
]
