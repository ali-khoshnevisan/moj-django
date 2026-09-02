import csv
import json
import random
import os
import zipfile
from rest_framework import status
from django.db.models import Max
from django.conf import settings
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action
from rest_framework.response import Response
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.exceptions import PermissionDenied
from instagrapi import Client
from instagrapi.exceptions import (
    TwoFactorRequired, BadCredentials, ChallengeRequired, LoginRequired,
    BadPassword, FeedbackRequired, AccountSuspended, PleaseWaitFewMinutes,
    ClientError,
)
from .models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostMediaModel
from .serializers import ProfileSerializer, ActionSerializer, CampaignSerializer
from accounts.permissions import IsActiveUser

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 10


class ProfileFilter(django_filters.FilterSet):
    class Meta:
        model = ProfileModel
        fields = ["social_media", "status"]


class ProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsActiveUser]
    serializer_class = ProfileSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProfileFilter
    skip_active_check = False

    def get_queryset(self):
        return ProfileModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"], url_path="max_id")
    def max_id(self, request):
        max_id = ProfileModel.objects.aggregate(Max('id'))['id__max']
        if not max_id:
            max_id = 0

        return Response({"max_id": int(max_id) + 1})

    @action(detail=False, methods=["get"], url_path="allocate-port")
    def allocate_port(self, request):
        MIN_PORT = 10000
        MAX_PORT = 30000

        last_profile = ProfileModel.objects.exclude(proxy__isnull=True).order_by('-id').first()

        last_port = MIN_PORT - 1

        if last_profile and isinstance(last_profile.proxy, dict) and 'port' in last_profile.proxy:
            try:
                last_port = int(last_profile.proxy['port'])
            except ValueError:
                pass

        next_port = last_port + 1

        print('next_port', next_port)

        if next_port > MAX_PORT:
            next_port = MIN_PORT

        return Response({"allocated_port": next_port})

    @action(detail=False, methods=["get"], url_path="random-twitter-bot")
    def get_twitter_bot(self, request):
        bots = self.get_queryset().filter(social_media='twitter')
        bot = random.choice(bots)
        return Response(self.serializer_class(bot).data)

    @action(detail=False, methods=["post"], url_path='create-twitter-profile')
    def create_twitter_profile(self, request):
        zip_file = request.FILES.get('zip_file')
        if not zip_file:
            return Response({"message": "you have to send zip file"}, status=400)

        country = request.data.get("country")
        if not country:
            return Response({"message": "you have to send country"}, status=400)

        firefox_profile_path = self.download_and_unzip(zip_file)
        data = dict(request.data)
        data.update(firefox_profile_path=firefox_profile_path)
        ser_data = self.serializer_class(data)
        if ser_data.is_valid():
            account = ser_data.save(user=request.user)
            with open(settings.PROFILES_CSV_PATH, 'a', newline="") as f:
                writer = csv.writer(f)
                writer.writerow([firefox_profile_path, int(account.pk) + 50000, country])

            return Response(ser_data.validated_data)
        return Response(ser_data.errors)

    def download_and_unzip(self, zip_file):
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(settings.PROFILE_DIR)
            first_file = zip_ref.namelist()[0]
            absolute_path = os.path.abspath(os.path.join(settings.PROFILE_DIR, first_file))
            if absolute_path.endswith('/'):
                absolute_path = absolute_path[:-1]
            return absolute_path


class ActionFilter(django_filters.FilterSet):
    after = django_filters.DateTimeFilter(
        field_name="last_update",
        lookup_expr="gte"
    )

    before = django_filters.DateTimeFilter(
        field_name="last_update",
        lookup_expr="lte"
    )

    send_date_after = django_filters.DateTimeFilter(
        field_name="send_date",
        lookup_expr="gte"
    )

    send_date_before = django_filters.DateTimeFilter(
        field_name="send_date",
        lookup_expr="lte"
    )

    platform = django_filters.CharFilter(
        field_name="bot__platform",
        lookup_expr="iexact"
    )

    actions = django_filters.BaseInFilter(
        field_name="action",
        lookup_expr="in"
    )

    class Meta:
        model = ActionModel
        fields = ["social_media", "action", "status", "bot"]


class ActionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsActiveUser]
    serializer_class = ActionSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ActionFilter

    def get_queryset(self):
        return ActionModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        bot = serializer.validated_data.get('bot')
        if bot is not None and bot.user_id != self.request.user.id:
            raise PermissionDenied("You don't own this bot.")
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        data = request.data
        bots = data.get('bot')

        if isinstance(bots, list):
            if not bots:
                return Response(
                    {"bot": ["You must select at least one bot."]},
                    status=status.HTTP_400_BAD_REQUEST
                )

            created_actions = []
            errors = []

            for bot_id in bots:
                action_data = data.copy()

                action_data['bot'] = bot_id

                serializer = self.get_serializer(data=action_data)

                if serializer.is_valid():
                    try:
                        self.perform_create(serializer)
                        created_actions.append(serializer.data)
                    except PermissionDenied as exc:
                        errors.append({"bot_id": bot_id, "errors": {"bot": [str(exc)]}})
                else:
                    errors.append({"bot_id": bot_id, "errors": serializer.errors})

            if errors and not created_actions:
                return Response(errors, status=status.HTTP_400_BAD_REQUEST)

            return Response(created_actions, status=status.HTTP_201_CREATED)

        return super().create(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path='count')
    def count(self, request):
        count = self.filter_queryset(self.get_queryset()).count()
        return Response({"count": count})

    @action(detail=False, methods=["get"], url_path="last-post")
    def last_post(self, request):
        last_post = self.get_queryset().filter(
            status__in=["requested", "pending"],
            action="post",
            social_media=request.query_params.get("social-media")
        ).order_by("send_date").first()
        return Response({
            "last_post": self.serializer_class(last_post).data if last_post else None
        })


class CampaignViewSet(viewsets.ModelViewSet):
    permission_classes = [IsActiveUser]
    serializer_class = CampaignSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return CampaignSocialMediaModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        bots = serializer.validated_data.get('bots', [])
        foreign_bots = [bot.id for bot in bots if bot.user_id != self.request.user.id]
        if foreign_bots:
            raise PermissionDenied(f"You don't own bot(s): {foreign_bots}")
        serializer.save(user=self.request.user)


class PostSocialMediaView(APIView):
    permission_classes = [IsActiveUser]

    def post(self, request):
        media_files = request.FILES.getlist("medias")
        media_types = request.data.getlist("media_types")

        if len(media_files) != len(media_types):
            return Response({"error": "media_files count must match media_types count"}, status=400)

        bot_id = int(request.data.get("bot"))
        if not ProfileModel.objects.filter(id=bot_id, user=request.user).exists():
            return Response({"bot": "Invalid bot for this user."}, status=400)

        action = ActionModel.objects.create(
            user=request.user,
            social_media=request.data.get("social_media"),
            action="post",
            bot_id=bot_id,
            text=str(request.data.get("text")),
            working=False
        )

        for file, media_type in zip(media_files, media_types):
            PostMediaModel.objects.create(
                action=action,
                media=file,
                media_type=media_type
            )
        action.working = True
        action.save()

        serializer = ActionSerializer(action)

        return Response(serializer.data, status=201)


PROXY_HOST = "proxy.ghostvps.com"
PROXY_PASSWORD = "92964b4ea532a8e1"
PROXY_USERNAME_PREFIX = "b8f3fab422699782c1f0"
LOGIN_MIN_PORT = 10000
LOGIN_MAX_PORT = 30000


def _allocate_login_port():
    last_profile = ProfileModel.objects.exclude(proxy__isnull=True).order_by('-id').first()

    last_port = LOGIN_MIN_PORT - 1
    if last_profile and isinstance(last_profile.proxy, dict) and 'port' in last_profile.proxy:
        try:
            last_port = int(last_profile.proxy['port'])
        except ValueError:
            pass

    next_port = last_port + 1
    if next_port > LOGIN_MAX_PORT:
        next_port = LOGIN_MIN_PORT

    return next_port


class InstagramLoginView(APIView):
    permission_classes = [IsActiveUser]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        totp_seed = request.data.get("totp")
        country = request.data.get("country")

        if not username or not password:
            return Response({"error": "username and password are required"}, status=400)
        if not country:
            return Response({"error": "country is required"}, status=400)

        port = _allocate_login_port()
        proxy_dsn = (
            f"{PROXY_USERNAME_PREFIX}__cr.{country};sessttl.120:"
            f"{PROXY_PASSWORD}@{PROXY_HOST}:{port}"
        )

        cl = Client()
        cl.set_proxy(proxy_dsn)

        verification_code = ""
        if totp_seed:
            try:
                verification_code = Client.totp_generate_code(totp_seed)
            except Exception as e:  # noqa: BLE001
                return Response({
                    "error": "could not generate a verification code from the provided totp seed",
                    "detail": str(e)[:500],
                }, status=400)

        try:
            cl.login(username, password, verification_code=verification_code)

        except TwoFactorRequired as e:
            return Response({
                "error": "two_factor_required",
                "message": "This account requires a 2FA code. Provide 'totp' (the TOTP seed).",
                "detail": str(e)[:500],
            }, status=401)

        except BadPassword as e:
            return Response({
                "error": "bad_password",
                "message": "Instagram rejected the password.",
                "detail": str(e)[:500],
            }, status=401)

        except BadCredentials as e:
            return Response({
                "error": "bad_credentials",
                "message": "Username or password is invalid or missing.",
                "detail": str(e)[:500],
            }, status=401)

        except ChallengeRequired as e:
            return Response({
                "error": "challenge_required",
                "message": "Instagram requires manual verification (checkpoint) for this account.",
                "detail": str(e)[:500],
            }, status=401)

        except AccountSuspended as e:
            return Response({
                "error": "account_suspended",
                "message": "This Instagram account is suspended.",
                "detail": str(e)[:500],
            }, status=403)

        except FeedbackRequired as e:
            return Response({
                "error": "feedback_required",
                "message": "Instagram is rate-limiting/throttling this account or IP.",
                "detail": str(e)[:500],
            }, status=429)

        except PleaseWaitFewMinutes as e:
            return Response({
                "error": "please_wait",
                "message": "Instagram asked to wait a few minutes before retrying.",
                "detail": str(e)[:500],
            }, status=429)

        except LoginRequired as e:
            return Response({
                "error": "login_required",
                "message": "Instagram rejected the session unexpectedly.",
                "detail": str(e)[:500],
            }, status=401)

        except ClientError as e:
            return Response({
                "error": "instagrapi_error",
                "message": "An unexpected Instagram API error occurred.",
                "detail": str(e)[:500],
            }, status=502)

        except Exception as e:  # noqa: BLE001
            return Response({
                "error": "unexpected_error",
                "detail": str(e)[:500],
            }, status=500)

        session_dict = cl.get_settings()
        session_json_string = json.dumps(session_dict)

        return Response({
            "session": session_json_string,
            "port": port,
        }, status=200)