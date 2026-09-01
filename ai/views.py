import requests
from django.conf import settings
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from .models import AIModel
from .serializers import AISerializer


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 10


class AIViewSet(viewsets.ModelViewSet):
    queryset = AIModel.objects.all()
    serializer_class = AISerializer
    pagination_class = StandardResultsSetPagination

    def perform_create(self, serializer):
        task = serializer.save()

        queue = task.ai_type
        if not task.comment_details and not task.post_details:
            queue = queue + "-fast"

        try:
            print('task', task)
            response = requests.post(
                settings.CREATE_TASK_CORE_SERVICE_URL,
                json={
                    "worker_type": queue,
                    "data": {"text": task.request}
                },
                timeout=10
            ).json()
            print('response:', response)

            task.task_id = response.get('task_id')
            task.status = 'pending'
            task.save()

        except Exception as e:
            print(f"error in sending to core:{e}")
            task.status = 'failed'
            task.save()