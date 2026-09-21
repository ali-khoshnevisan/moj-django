from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'social-media'

router = DefaultRouter()
router.register(r'profile', views.ProfileViewSet, basename='profile')
# router.register(r'profile-log', views.ProfileLogViewSet, basename='profile_log')
router.register(r'actions', views.ActionViewSet, basename='action')
router.register(r'campaign', views.CampaignViewSet, basename='campaign')

urlpatterns = [
    path('', include(router.urls), name='router'),
    path('post/', views.PostSocialMediaView.as_view(), name="post_action"),
    path('post/<int:action_id>/', views.AddPostMediaView.as_view(), name="add_post_media"),
    path('post/<int:action_id>/update/', views.UpdatePostView.as_view(), name="update_post"),
    path('instagram-login/', views.InstagramLoginView.as_view(), name="instagram_login"),
]