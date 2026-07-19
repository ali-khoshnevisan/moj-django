from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.views import Response
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
    queryset = AccountModel.objects.all()
    serializer_class = AccountSerializer
    pagination_class = StandardResultsSetPagination

    def perform_create(self, serializer):
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
    queryset = PostModel.objects.all()
    serializer_class = PostSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = PostFilter

    def get_queryset(self):
        return (
            PostModel.objects
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
    queryset = WebSinglePostModel.objects.all()
    serializer_class = WebSinglePostSerializer
    pagination_class = StandardResultsSetPagination


class TelegramBotView(viewsets.ModelViewSet):
    queryset = TelegramModel.objects.all()
    serializer_class = TelegramBotSerializer
    pagination_class = StandardResultsSetPagination


class TelegramSendPostView(viewsets.ModelViewSet):
    queryset = TelegramSendPost.objects.all()
    serializer_class = TelegramSendPostSerializer
    pagination_class = StandardResultsSetPagination

    @action(detail=False, methods=["get"], url_path="last-post")
    def last_post(self, request):
        last_post = self.queryset.filter(status="requested").order_by("send_date").first()
        return Response({"last_post": self.serializer_class(last_post).data})
