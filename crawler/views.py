from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import Response
from rest_framework.permissions import IsAuthenticated
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from .models import AccountModel, PostModel, WebSinglePostModel, TelegramModel, TelegramSendPost
from .serializers import AccountSerializer, PostSerializer, WebSinglePostSerializer, TelegramBotSerializer, \
    TelegramSendPostSerializer
from django.db.models import Case, When, Value, IntegerField
from .tasks import telegram_worker_task

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 10


class AccountViewSet(viewsets.ModelViewSet):
    # permission_classes = [IsAuthenticated]
    queryset = AccountModel.objects.all()
    serializer_class = AccountSerializer
    pagination_class = StandardResultsSetPagination

    # def get_queryset(self):
    #     return AccountModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        # account = serializer.save(user=self.request.user)
        account = serializer.save()

        if account.platform == 'telegram' and account.status == 'requested':
            task = telegram_worker_task.delay(account.id, account.url)

            account.task_id = str(task.id)
            account.save()

    def perform_update(self, serializer):
        account = serializer.save()

        if account.platform == 'telegram' and account.status == 'requested' and not account.task_id:
            task = telegram_worker_task.delay(account.id, account.url)
            account.task_id = str(task.id)
            account.save()


class PostFilter(django_filters.FilterSet):
    after = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="gte"
    )

    before = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="lte"
    )

    platform = django_filters.CharFilter(
        field_name="account__platform",
        lookup_expr="iexact"
    )

    account_url = django_filters.CharFilter(
        field_name="account__url",
        lookup_expr="iexact"
    )

    class Meta:
        model = PostModel
        fields = ["account"]


class PostViewSet(viewsets.ModelViewSet):
    # permission_classes = [IsAuthenticated]
    serializer_class = PostSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = PostFilter

    def get_queryset(self):
        return (
            PostModel.objects
            # .filter(account__user=self.request.user)
            .annotate(
                priority=Case(
                    When(status="ai-generated", then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by("priority", "-created_at")
        )


class WebSinglePostView(viewsets.ModelViewSet):
    # permission_classes = [IsAuthenticated]
    serializer_class = WebSinglePostSerializer
    pagination_class = StandardResultsSetPagination

    # def get_queryset(self):
    #     return WebSinglePostModel.objects.filter(user=self.request.user)
    #
    # def perform_create(self, serializer):
    #     serializer.save(user=self.request.user)


class TelegramBotView(viewsets.ModelViewSet):
    queryset = TelegramModel.objects.all()
    # permission_classes = [IsAuthenticated]
    serializer_class = TelegramBotSerializer
    pagination_class = StandardResultsSetPagination

    # def get_queryset(self):
    #     return TelegramModel.objects.filter(user=self.request.user)
    #
    # def perform_create(self, serializer):
    #     serializer.save(user=self.request.user)


class TelegramSendPostView(viewsets.ModelViewSet):
    # permission_classes = [IsAuthenticated]
    queryset = TelegramSendPost.objects.all()
    serializer_class = TelegramSendPostSerializer
    pagination_class = StandardResultsSetPagination

    def create(self, request, *args, **kwargs):
        data = request.data
        medias = request.FILES.getlist('medias')
        media_types = request.data.getlist('media_types')

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        post = serializer.save()

        from .models import TelegramPostMedia
        for i, media in enumerate(medias):
            media_type = media_types[i]
            TelegramPostMedia.objects.create(post=post, media=media, media_type=media_type)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def get_queryset(self):
        return TelegramSendPost.objects.filter(bot__user=self.request.user)

    @action(detail=False, methods=["get"], url_path="last-post")
    def last_post(self, request):
        last_post = self.queryset.filter(status="requested").order_by("send_date").first()
        return Response({"last_post": self.serializer_class(last_post).data})
        # last_post = self.get_queryset().filter(status="requested").order_by("send_date").first()
        # return Response({"last_post": self.serializer_class(last_post).data if last_post else None})