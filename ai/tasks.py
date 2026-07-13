from urllib.parse import urljoin
import requests
from django.conf import settings
from .models import AIModel


def ai_process():
    print("START AI TASKS MANAGER")
    requested_tasks = AIModel.objects.filter(status='requested')
    for task in requested_tasks:
        queue = task.ai_type
        if not task.comment_details and not task.post_details:
            queue = queue + "-fast"
        try:
            response = requests.post(settings.CREATE_TASK_CORE_SERVICE_URL,
                                     json={"worker_type": queue,
                                           "data": {"text": task.request}}).json()
            task_id = response['task_id']
            task.task_id = task_id
            task.status = 'pending'
            task.save()

        except Exception as e:
            print(e)

    print("FINISH AI TASKS MANAGER")
