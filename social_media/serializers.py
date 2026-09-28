from rest_framework import serializers
from .models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostCampaignModel, PostMediaModel


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfileModel
        fields = '__all__'
        extra_kwargs = {
            'user': {'read_only': True},
        }

        def validate(self, attrs):
            social_media = attrs.get(
                'social_media',
                self.instance.social_media if self.instance else None
            )

            username = attrs.get(
                'username',
                self.instance.username if self.instance else None
            )

            exists = ProfileModel.objects.filter(
                social_media=social_media,
                username=username
            )

            if self.instance:
                exists = exists.exclude(pk=self.instance.pk)

            if exists.exists():
                raise serializers.ValidationError({
                    'username': (
                        f'This account is already registered for '
                        f'{social_media}.'
                    )
                })

            return attrs
# class ProfileLogSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = ProfileLogModel
#         fields = '__all__'


class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMediaModel
        fields = "__all__"


class CampaignSerializer(serializers.ModelSerializer):
    posts_objects = serializers.SerializerMethodField()
    actions_objects = serializers.SerializerMethodField()
    bots_objects = serializers.SerializerMethodField()

    class Meta:
        model = CampaignSocialMediaModel
        fields = "__all__"
        extra_kwargs = {
            'user': {'read_only': True},
        }

    def get_posts_objects(self, obj):
        return PostCampaignSerializer(obj.posts_objects.all(), many=True).data

    def get_actions_objects(self, obj):
        return ActionSerializer(obj.actions_objects.all(), many=True).data

    def get_bots_objects(self, obj):
        return ProfileSerializer(obj.bots.all(), many=True).data

class CampaignBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignSocialMediaModel
        fields = [
            "id",
            "campaign_description",
        ]

class ActionSerializer(serializers.ModelSerializer):
    campaign = CampaignBriefSerializer(read_only=True)
    bot_info = serializers.SerializerMethodField()
    medias = PostMediaSerializer(many=True, read_only=True)

    class Meta:
        model = ActionModel
        fields = "__all__"
        extra_kwargs = {
            'user': {'read_only': True},
        }

    def get_bot_info(self, obj):
        return ProfileSerializer(obj.bot).data


class PostCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostCampaignModel
        fields = "__all__"

