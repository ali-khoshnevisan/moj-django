import csv
import random
import os
import zipfile

import requests
from django.db.models import Max
from django.conf import settings
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import action
from rest_framework.response import Response
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import ProfileModel, ActionModel, CampaignSocialMediaModel, PostMediaModel
from .serializers import ProfileSerializer, ActionSerializer, CampaignSerializer
from rest_framework.permissions import AllowAny
from accounts.permissions import IsActiveUser

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 10


class ProfileFilter(django_filters.FilterSet):
    class Meta:
        model = ProfileModel
        fields = ["social_media"]


class ProfileViewSet(viewsets.ModelViewSet):
    queryset = ProfileModel.objects.all()
    permission_classes = [AllowAny]
    serializer_class = ProfileSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProfileFilter
    skip_active_check = False

    # def get_queryset(self):
    #     return ProfileModel.objects.filter(user=self.request.user)
    #
    # def perform_create(self, serializer):
    #     serializer.save(user=self.request.user)
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

        if next_port > MAX_PORT:
            next_port = MIN_PORT

        return Response({"allocated_port": next_port})

    @action(detail=False, methods=["get"], url_path="random-twitter-bot")
    def get_twitter_bot(self, request):
        bots = self.queryset.filter(social_media='twitter')
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
            account = ser_data.save()
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
    queryset = ActionModel.objects.all()
    serializer_class = ActionSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ActionFilter

    def get_queryset(self):
        return ActionModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"], url_path='count')
    def count(self, request):
        count = self.filter_queryset(self.get_queryset()).count()
        return Response({"count": count})

    @action(detail=False, methods=["get"], url_path="last-post")
    def last_post(self, request):
        print(request.query_params.get("social-media"))
        last_post = self.queryset.filter(status__in=["requested", "pending"], action="post",
                                         social_media=request.query_params.get("social-media")).order_by("send_date").first()
        return Response({"last_post": self.serializer_class(last_post).data})


class CampaignViewSet(viewsets.ModelViewSet):
    permission_classes = [IsActiveUser]
    queryset = CampaignSocialMediaModel.objects.all()
    serializer_class = CampaignSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return CampaignSocialMediaModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PostSocialMediaView(APIView):
    permission_classes = [IsActiveUser]

    def post(self, request):
        media_files = request.FILES.getlist("medias")
        media_types = request.data.getlist("media_types")

        if len(media_files) != len(media_types):
            return Response({"error": "media_files count must match media_types count"}, status=400)

        action = ActionModel.objects.create(
            # user = request.user,
            social_media=request.data.get("social_media"),
            action="post",
            bot_id=int(request.data.get("bot")),
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
