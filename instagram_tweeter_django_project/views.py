import os
import requests
from django.conf import settings
from django.utils import timezone
from django.core.files import File
from django.core.files.base import ContentFile
from rest_framework.views import APIView, Response
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from ai.models import AIModel
from crawler.models import AccountModel, PostModel, WebSinglePostModel
from social_media.models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostCampaignModel


class AllowCoreServerIP(BasePermission):
    def has_permission(self, request, view):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')

        return ip == '91.107.232.169'

class TaskSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    worker_type = serializers.CharField()
    data = serializers.JSONField(allow_null=True)
    status = serializers.CharField()
    result = serializers.JSONField(allow_null=True)


class TaskUpdateManager(APIView):
    authentication_classes = []
    permission_classes = [AllowCoreServerIP]
    serializer_class = TaskSerializer
    model_determiner_dict = {
        "chatgpt": AIModel,
        "chatgpt-fast": AIModel,
        "telegram-crawler": AccountModel,
        "web-crawler": AccountModel,
        "web-crawler-single-post": PostModel,
        "web-crawler-single-post-test": WebSinglePostModel,
        "instagram-check-profile": ProfileModel,
        "instagram-profile": [ProfileModel, CampaignSocialMediaModel],
        "twitter-check-profile": ProfileModel,
        "twitter-profile": ProfileModel,
        "instagram-like": ActionModel,
        "instagram-post": ActionModel,
        "instagram-follow": ActionModel,
        "instagram-direct": ActionModel,
        "twitter-like": ActionModel,
        "twitter-post": ActionModel,
        "twitter-follow": ActionModel,
        "twitter-direct": ActionModel,
        "instagram-comment": ActionModel,
        "twitter-comment": ActionModel,
        "instagram-comments": PostCampaignModel,
        "twitter-comments": PostCampaignModel,
    }

    def post(self, request):
        res_data = self.serializer_class(data=request.data)
        if not res_data.is_valid():
            print("not valid")
            return Response(res_data.errors, status=400)
        valid_data = res_data.validated_data

        task_id = valid_data['task_id']
        worker_type = valid_data['worker_type']
        status = valid_data['status']
        result = valid_data['result']
        model = self.model_determiner(worker_type)
        if not model:
            return Response({"message": "This worker type is not allowed"}, status=400)
        obj = self.find_obj(model, task_id)
        if not obj:
            return Response({"message": "This task id is not found"})
        method = self.find_method(worker_type)
        if not method:
            return Response({"message": "This worker type is not allowed"}, status=400)
        method(obj, status, result)
        return Response({"message": "ok"})

    def model_determiner(self, worker):
        return self.model_determiner_dict.get(worker)

    def find_obj(self, model, task_id):
        if isinstance(model, list):
            for m in model:
                if hasattr(m, "task_id"):
                    try:
                        return m.objects.get(task_id=task_id)
                    except Exception as e:
                        print(e)
                else:
                    try:
                        for obj in m.objects.all():
                            if task_id in (obj.task_ids or []):
                                task_ids = list(obj.task_ids)
                                task_ids.remove(task_id)

                                obj.task_ids = task_ids
                                obj.save()

                                return obj
                    except Exception as e:
                        print(e)

        else:
            try:
                return model.objects.get(task_id=task_id)
            except Exception as e:
                print(e)

    def find_method(self, worker):
        match worker:
            case "chatgpt":
                return self.ai_response
            case "chatgpt-fast":
                return self.ai_response
            case "telegram-crawler":
                return self.crawler_response
            case "web-crawler":
                return self.crawler_response
            case "web-crawler-single-post":
                return self.post_crawler_response
            case "web-crawler-single-post-test":
                return self.post_test_crawler_response
            case "instagram-check-profile":
                return self.check_profile_response
            case "twitter-check-profile":
                return self.check_profile_response
            case "instagram-profile":
                return self.profile_response
            case "twitter-profile":
                return self.profile_response
            case "instagram-like":
                return self.action_response
            case "twitter-like":
                return self.action_response
            case "instagram-follow":
                return self.action_response
            case "twitter-follow":
                return self.action_response
            case "instagram-post":
                return self.action_response
            case "twitter-post":
                return self.action_response
            case "instagram-direct":
                return self.action_response
            case "twitter-direct":
                return self.action_response
            case "instagram-comment":
                return self.action_response
            case "twitter-comment":
                return self.action_response
            case "instagram-comments":
                return self.post_campaign_response
            case "twitter-comments":
                return self.post_campaign_response

    def ai_response(self, task, status, result):

        try:
            if status == settings.FAILED_CORE_TASK_STATUS:
                if task.failed_count < 3:
                    task.task_id = None
                    task.status = "failed"
                    task.failed_count += 1
                    task.save()
                else:
                    task.status = "requested"
                    task.task_id = None
                    task.failed_count += 1
                    task.save()
            elif status == settings.SUCCESS_CORE_TASK_STATUS:
                task.response = result['text']
                task.status = status
                task.comment_answer()
                task.post_answer()
                task.save()

        except Exception as e:
            print(e)

    def crawler_response(self, account, status, result):
        if status == settings.FAILED_CORE_TASK_STATUS:
            account.task_id = None
            account.save()
        elif status == settings.SUCCESS_CORE_TASK_STATUS:
            account.task_id = None
            account.last_update = timezone.now()
            account.status = 'enable'
            account.save()
            for post in result:
                try:
                    if account.platform == "telegram":
                        _post = PostModel.objects.create(account=account,
                                                         url=post.get('url'),
                                                         title=post.get('title'),
                                                         text=post.get('text'),
                                                         media=post.get('media'),
                                                         status="created")
                        if post.get("media_path"):
                            path = post.get("media_path")
                            with open(path, "rb") as f:
                                _post.media_file.save(
                                    os.path.basename(path),
                                    File(f),
                                    save=True
                                )
                    else:
                        _post = PostModel.objects.create(account=account,
                                                         url=post,
                                                         status="requested")
                except Exception as e:
                    print(e)

    def post_crawler_response(self, post, status, result):
        if status == settings.FAILED_CORE_TASK_STATUS:
            post.task_id = None
            post.status = "trash"
            post.save()

        elif status == settings.SUCCESS_CORE_TASK_STATUS:
            post.task_id = None
            post.text = result.get('text')
            post.title = result.get('title')
            post.media = result.get('media')
            post.status = "created" if result.get('text') else "trash"
            post.save()

    def post_test_crawler_response(self, post, status, result):
        if status == settings.FAILED_CORE_TASK_STATUS:
            post.task_id = None
            post.status = "failed"
            post.save()

        elif status == settings.SUCCESS_CORE_TASK_STATUS:
            post.status = 'success'
            post.title = result.get('title')
            post.text = result.get('text')
            post.media = result.get('media')
            post.task_id = None
            post.save()

    def check_profile_response(self, profile, status, result):
        if status == settings.FAILED_CORE_TASK_STATUS:
            profile.task_id = None
            profile.last_update = timezone.now()
            profile.status = "requested"
            profile.save()
        else:
            login_status = result['login_status']
            if login_status:
                profile.status = 'grab-profile'
                profile.task_id = None
                profile.save()
            else:
                profile.status = "profile-is-not-login"
                profile.task_id = None
                profile.save()

    def profile_response(self, profile, status, result):
        if isinstance(profile, ProfileModel):
            if status == settings.FAILED_CORE_TASK_STATUS:
                profile.task_id = None
                profile.last_update = timezone.now()
                profile.save()
            else:
                profile.followers = result['followers']
                profile.followings = result['following']
                profile.description = result['bio']
                profile.posts_count = result['posts']
                profile.profile_image = result['avatar']
                profile.status = 'added'
                profile.task_id = None
                profile.save()
                url = result['avatar']
                response = requests.get(url)
                profile.image.save(
                    f"profile_{profile.id}.png",
                    ContentFile(response.content),
                    save=True
                )
        elif isinstance(profile, CampaignSocialMediaModel):
            profile.posts = list(set(result["last_12_posts"] + profile.posts))
            profile.save()

    def action_response(self, task, status, result):
        task.status = status
        task.task_id = None
        task.save()

    def post_campaign_response(self, post, status, result):
        if status == settings.FAILED_CORE_TASK_STATUS:
            post.task_id = None
            post.status = "failed"
            post.save()
        else:

            post.comments = result
            post.status = "success"
            post.task_id = None
            post.save()
