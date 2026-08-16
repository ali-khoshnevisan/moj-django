from rest_framework import serializers
from .models import AccountModel, PostModel, WebSinglePostModel, TelegramModel, TelegramSendPost


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountModel
        fields = '__all__'
        extra_kwargs = {
            'task_id': {'write_only': True},
            'user': {'read_only': True},
        }


class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostModel
        fields = '__all__'


class WebSinglePostSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebSinglePostModel
        fields = '__all__'
        extra_kwargs = {
            'user': {'read_only': True},
        }


class TelegramBotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramModel
        fields = '__all__'
        extra_kwargs = {
            'user': {'read_only': True},
        }


class TelegramSendPostSerializer(serializers.ModelSerializer):
    bot_info = serializers.SerializerMethodField()

    class Meta:
        model = TelegramSendPost
        fields = '__all__'

    def get_bot_info(self, obj):
        return TelegramBotSerializer(obj.bot).data