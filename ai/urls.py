from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'ai'

router = DefaultRouter()
router.register('', views.AIViewSet)

urlpatterns = [
    path('', include(router.urls), name='router'),
]