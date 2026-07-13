"""
URL configuration for instagram_tweeter_django_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    path('api/update-task/', views.TaskUpdateManager.as_view()),
    path('api/admin/', admin.site.urls),
    path('api/ai/', include('ai.urls', namespace='accounts')),
    path('api/accounts/', include('accounts.urls', namespace='ai')),
    path('api/crawler/', include('crawler.urls', namespace='crawler')),
    path('api/social-media/', include('social_media.urls', namespace='social-media')),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
