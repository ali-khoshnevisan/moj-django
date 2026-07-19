import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'instagram_tweeter_django_project.settings')

app = Celery('instagram_tweeter_django_project')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()