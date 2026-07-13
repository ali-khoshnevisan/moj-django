from rest_framework import serializers
from .models import AIModel


class AISerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModel
        exclude = ['task_id']
        extra_kwargs = {
            "status": {"read_only": True}
        }
