import os
import requests
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.core.files import File
from django.core.files.base import ContentFile
from django.db.models import Count
from django.db.models.functions import TruncDate
from rest_framework.views import APIView, Response
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from ai.models import AIModel
from crawler.models import (
    AccountModel, PostModel, WebSinglePostModel, TelegramSendPost, TelegramModel,
    account_status_choices, post_status_choices, telegram_model_status_choices,
)
from social_media.models import (
    ProfileModel, ActionModel, CampaignSocialMediaModel, PostCampaignModel,
    social_media_choices, profile_status_choices, action_status_choices,
)
from accounts.permissions import IsActiveUser


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
        # "telegram-crawler": AccountModel,
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

        if status == settings.DISABLE_PROFILE_STATUS and not isinstance(
            obj, ActionModel
        ):
            return Response(
                {"message": "disable_profile is not applicable to this worker type"},
                status=400,
            )

        method = self.find_method(worker_type)
        if not method:
            return Response({"message": "This worker type is not allowed"}, status=400)
        method(obj, status, result)
        return Response({"message": "ok"})

    def disable_profile(self, profile):
        if not profile:
            return
        ProfileModel.objects.filter(pk=profile.pk).update(
            status=settings.PROFILE_NOT_LOGIN_STATUS,
        )

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
            # case "telegram-crawler":
            #     return self.crawler_response
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
            if status == settings.PROFILE_NOT_LOGIN_STATUS:
                profile.status = settings.PROFILE_NOT_LOGIN_STATUS
                profile.task_id = None
                profile.last_update = timezone.now()
                profile.save()
            elif status == settings.FAILED_CORE_TASK_STATUS:
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
            if status == settings.PROFILE_NOT_LOGIN_STATUS:
                self.disable_profile(profile.bots.first())
                profile.status = 'failed'
                profile.task_ids = []
                profile.save()
            else:
                profile.posts = list(set(result["last_12_posts"] + profile.posts))
                if result["posts_count"] > 0 and len(result["last_12_posts"]) == 0:
                    profile.status = 'private'
                else: profile.status = status
                profile.save()

    def action_response(self, task, status, result):
        if status == settings.DISABLE_PROFILE_STATUS:
            self.disable_profile(task.bot)
            task.status = 'failed'
            task.task_id = None
            task.save()
            return

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


class DashboardSummaryView(APIView):
    """
    Single aggregated endpoint for the frontend dashboard/home page, scoped
    to the requesting user. Pulls counts and a small "recent activity" slice
    from crawler, social_media, and the current account — avoids the
    frontend making 5+ separate list calls just to compute totals.
    """
    permission_classes = [IsActiveUser]

    def get(self, request):
        user = request.user

        return Response({
            "account": self._account_overview(user),
            "crawler": self._crawler_summary(user),
            "social_media": self._social_media_summary(user),
            "campaigns": self._campaigns_summary(user),
            "upcoming": self._upcoming_summary(user),
            "trends": {
                "activity": self._activity_trend(user),
                "schedule": self._schedule_trend(user),
            },
        })

    @staticmethod
    def _breakdown(queryset, choices, field_name="status"):
        # Always includes every choice (even with count 0) so the frontend
        # doesn't have to guess which statuses exist.
        breakdown = {choice[0]: 0 for choice in choices}
        counts = queryset.values(field_name).annotate(count=Count("id"))
        for row in counts:
            breakdown[row[field_name]] = row["count"]
        return breakdown

    @staticmethod
    def _account_overview(user):
        return {
            "email": getattr(user, "email", None),
            "full_name": user.get_full_name() if hasattr(user, "get_full_name") else None,
            "date_joined": getattr(user, "date_joined", None),
            "is_active": getattr(user, "is_active", True),
        }

    def _crawler_summary(self, user):
        accounts_qs = AccountModel.objects.filter(user=user)
        posts_qs = PostModel.objects.filter(account__user=user)

        return {
            "total_accounts": accounts_qs.count(),
            "accounts_by_status": self._breakdown(accounts_qs, account_status_choices),
            "total_posts": posts_qs.count(),
            "posts_by_status": self._breakdown(posts_qs, post_status_choices),
            "recent_posts": [
                {
                    "id": p.id,
                    "title": p.title,
                    "url": p.url,
                    "status": p.status,
                    "created_at": p.created_at,
                    "account_platform": p.account.platform,
                }
                for p in posts_qs.select_related("account").order_by("-created_at")[:5]
            ],
        }

    def _social_media_summary(self, user):
        profiles_qs = ProfileModel.objects.filter(user=user)
        actions_qs = ActionModel.objects.filter(user=user)
        # NOTE: TelegramModel actually lives in crawler/models.py, not
        # social_media — included here anyway since it's conceptually a
        # "connected account" alongside Instagram/Twitter profiles.
        telegram_bots_qs = TelegramModel.objects.filter(user=user)

        return {
            "total_profiles": profiles_qs.count(),
            "profiles_by_platform": self._breakdown(profiles_qs, social_media_choices, field_name="social_media"),
            "profiles_by_status": self._breakdown(profiles_qs, profile_status_choices),
            "total_actions": actions_qs.count(),
            "actions_by_status": self._breakdown(actions_qs, action_status_choices),
            "recent_actions": [
                {
                    "id": a.id,
                    "action": a.action,
                    "social_media": a.social_media,
                    "status": a.status,
                    "send_date": a.send_date,
                    "bot_username": a.bot.username if a.bot else None,
                }
                for a in actions_qs.select_related("bot").order_by("-send_date")[:5]
            ],
            "total_telegram_bots": telegram_bots_qs.count(),
            "telegram_bots_by_status": self._breakdown(telegram_bots_qs, telegram_model_status_choices),
        }

    def _campaigns_summary(self, user):
        campaigns_qs = CampaignSocialMediaModel.objects.filter(user=user)

        return {
            "total_campaigns": campaigns_qs.count(),
            "active_campaigns": campaigns_qs.filter(working=True).count(),
            "campaigns_by_status": self._breakdown(campaigns_qs, action_status_choices),
        }

    def _upcoming_summary(self, user):
        """
        Everything with a future send_date that hasn't gone out yet:
        - social_media "post" actions still requested/pending
        - telegram sends still requested
        Combined and sorted so the frontend can show one unified "what's
        coming up" list plus a highlighted "next publish" item.
        """
        now = timezone.now()

        upcoming_actions_qs = (
            ActionModel.objects
            .filter(user=user, action="post", status__in=["requested", "pending"], send_date__gte=now)
            .select_related("bot")
            .order_by("send_date")
        )

        upcoming_telegram_qs = (
            TelegramSendPost.objects
            .filter(bot__user=user, status="requested", send_date__gte=now)
            .select_related("bot")
            .order_by("send_date")
        )

        upcoming_actions = [
            {
                "id": a.id,
                "source": "social_media",
                "platform": a.social_media,
                "label": a.bot.username if a.bot else "Unknown bot",
                "send_date": a.send_date,
                "status": a.status,
            }
            for a in upcoming_actions_qs[:10]
        ]

        upcoming_telegram = [
            {
                "id": t.id,
                "source": "telegram",
                "platform": "telegram",
                "label": t.bot.channel if t.bot else "Unknown channel",
                "send_date": t.send_date,
                "status": t.status,
            }
            for t in upcoming_telegram_qs[:10]
        ]

        combined = sorted(upcoming_actions + upcoming_telegram, key=lambda x: x["send_date"])
        due_within_24h = sum(1 for item in combined if item["send_date"] <= now + timedelta(hours=24))

        return {
            "total_scheduled": upcoming_actions_qs.count() + upcoming_telegram_qs.count(),
            "due_within_24h": due_within_24h,
            "next_publish": combined[0] if combined else None,
            "items": combined[:5],
        }

    def _activity_trend(self, user):
        """Last 14 days: crawled posts created vs. social actions completed, per day."""
        days = 14
        today = timezone.localdate()
        start_date = today - timedelta(days=days - 1)
        date_range = [start_date + timedelta(days=i) for i in range(days)]

        posts_by_day = dict.fromkeys(date_range, 0)
        for row in (
            PostModel.objects
            .filter(account__user=user, created_at__date__gte=start_date)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        ):
            posts_by_day[row["day"]] = row["count"]

        actions_by_day = dict.fromkeys(date_range, 0)
        for row in (
            ActionModel.objects
            .filter(user=user, status="success", send_date__date__gte=start_date)
            .annotate(day=TruncDate("send_date"))
            .values("day")
            .annotate(count=Count("id"))
        ):
            actions_by_day[row["day"]] = row["count"]

        return {
            "categories": [d.isoformat() for d in date_range],
            "posts": [posts_by_day[d] for d in date_range],
            "actions": [actions_by_day[d] for d in date_range],
        }

    def _schedule_trend(self, user):
        """Next 7 days: how many posts/telegram sends are already scheduled, per day."""
        days = 7
        today = timezone.localdate()
        end_date = today + timedelta(days=days - 1)
        date_range = [today + timedelta(days=i) for i in range(days)]

        scheduled_by_day = dict.fromkeys(date_range, 0)

        for row in (
            ActionModel.objects
            .filter(
                user=user, action="post", status__in=["requested", "pending"],
                send_date__date__gte=today, send_date__date__lte=end_date,
            )
            .annotate(day=TruncDate("send_date"))
            .values("day")
            .annotate(count=Count("id"))
        ):
            scheduled_by_day[row["day"]] += row["count"]

        for row in (
            TelegramSendPost.objects
            .filter(
                bot__user=user, status="requested",
                send_date__date__gte=today, send_date__date__lte=end_date,
            )
            .annotate(day=TruncDate("send_date"))
            .values("day")
            .annotate(count=Count("id"))
        ):
            scheduled_by_day[row["day"]] += row["count"]

        return {
            "categories": [d.isoformat() for d in date_range],
            "scheduled": [scheduled_by_day[d] for d in date_range],
        }