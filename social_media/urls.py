from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'social-media'

router = DefaultRouter()
router.register(r'profile', views.ProfileViewSet, basename='profile')
router.register(r'actions', views.ActionViewSet, basename='action')
router.register(r'campaign', views.CampaignViewSet, basename='campaign')

urlpatterns = [
    path('', include(router.urls), name='router'),
    path('post/', views.PostSocialMediaView.as_view(), name="post_action"),
]