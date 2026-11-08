"""Workspace-administrator mail status and retry controls."""

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Prefetch, Q

from bfg.core.permissions import IsWorkspaceAdmin
from bfg.common.models import EmailOutbox, EmailOutboxAttachment, EmailOutboxAttempt
from bfg.common.services.email_outbox import retry_email


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailOutboxAttachment
        fields = ['id', 'filename', 'content_type', 'size', 'sha256']


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailOutboxAttempt
        fields = ['number', 'state', 'error_code', 'started_at', 'finished_at']


class OutboxSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)
    attempts = AttemptSerializer(source='recent_attempts', many=True, read_only=True)

    class Meta:
        model = EmailOutbox
        fields = [
            'id', 'to_email', 'subject', 'state', 'attempt_count', 'next_attempt_at',
            'last_error_code', 'message_id', 'sent_at', 'created_at', 'attachments', 'attempts',
        ]


class OutboxPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


class OutboxListSerializer(OutboxSerializer):
    class Meta(OutboxSerializer.Meta):
        fields = [field for field in OutboxSerializer.Meta.fields if field != 'attempts']


class EmailOutboxViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OutboxSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    pagination_class = OutboxPagination
    http_method_names = ['get', 'post', 'head', 'options']

    def get_serializer_class(self):
        return OutboxListSerializer if self.action == 'list' else OutboxSerializer

    def get_queryset(self):
        queryset = EmailOutbox.all_objects.filter(workspace=self.request.workspace)
        state = self.request.query_params.get('state')
        if state:
            if state not in EmailOutbox.State.values:
                raise ValidationError({'state': 'Invalid email state.'})
            queryset = queryset.filter(state=state)
        query = self.request.query_params.get('q', '').strip()
        if query:
            queryset = queryset.filter(Q(to_email__icontains=query) | Q(subject__icontains=query))
        queryset = queryset.prefetch_related(
            Prefetch('attachments', queryset=EmailOutboxAttachment.objects.defer('content')),
        )
        if self.action != 'list':
            queryset = queryset.prefetch_related(Prefetch(
                'attempts', queryset=EmailOutboxAttempt.objects.order_by('-number')[:100],
                to_attr='recent_attempts',
            ))
        return queryset

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        message = self.get_object()
        if not retry_email(request.workspace, message.pk):
            return Response(
                {'code': 'email_not_retryable', 'detail': 'This email cannot be retried now.'},
                status=status.HTTP_409_CONFLICT,
            )
        message.refresh_from_db(fields=[
            'state', 'next_attempt_at', 'attempt_count', 'last_error_code', 'sent_at',
        ])
        return Response(self.get_serializer(message).data)
