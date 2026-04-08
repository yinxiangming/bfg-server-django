# -*- coding: utf-8 -*-
from django.utils.timezone import now
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.channels.models import (
    ChannelFAQRule,
    ExternalChannel,
    ExternalFeedback,
    ExternalListing,
    ExternalQuestion,
)
from apps.channels.serializers import (
    ChannelFAQRuleSerializer,
    ExternalChannelSerializer,
    ExternalFeedbackSerializer,
    ExternalListingSerializer,
    ExternalQuestionSerializer,
)


class ExternalChannelViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ExternalChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ExternalChannel.objects.filter(workspace=self.request.workspace)

    def perform_create(self, serializer):
        serializer.save(workspace=self.request.workspace)

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        """Test that the stored credentials are valid."""
        channel = self.get_object()
        from apps.channels.adapters import get_adapter

        try:
            adapter = get_adapter(channel)
            valid = adapter.validate_credentials()
        except Exception as exc:
            return Response({"valid": False, "detail": str(exc)}, status=status.HTTP_200_OK)

        if valid:
            channel.last_sync_at = now()
            channel.save(update_fields=["last_sync_at"])

        return Response({"valid": valid})

    @action(detail=True, methods=["post"], url_path="publish/(?P<product_id>[0-9]+)")
    def publish(self, request, pk=None, product_id=None):
        """Manually publish a product to this channel."""
        channel = self.get_object()
        from django.apps import apps

        Product = apps.get_model("shop", "Product")
        try:
            product = Product.objects.get(id=product_id, workspace=request.workspace)
        except Product.DoesNotExist:
            return Response({"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND)

        from apps.channels.services import ChannelListingService

        service = ChannelListingService(
            workspace=request.workspace,
            user=request.user,
            channel=channel,
        )
        try:
            listing = service.publish_product(product)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ExternalListingSerializer(listing).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def listings(self, request, pk=None):
        """List all listings for this channel."""
        channel = self.get_object()
        qs = ExternalListing.objects.filter(channel=channel).select_related("product")
        serializer = ExternalListingSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="field-spec")
    def field_spec(self, request, pk=None):
        """Return the adapter's FIELD_SPEC for frontend validation."""
        channel = self.get_object()
        from apps.channels.adapters import get_adapter

        try:
            adapter = get_adapter(channel)
            spec = adapter.FIELD_SPEC
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(spec)


class ExternalListingViewSet(
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ExternalListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ExternalListing.objects.filter(
            channel__workspace=self.request.workspace
        ).select_related("product", "channel")
        channel_id = self.request.query_params.get("channel")
        product_id = self.request.query_params.get("product")
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        """Manually end/withdraw a listing."""
        listing = self.get_object()
        from apps.channels.services import ChannelListingService

        service = ChannelListingService(
            workspace=request.workspace,
            user=request.user,
            channel=listing.channel,
        )
        try:
            service.handle_out_of_stock(listing)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ExternalListingSerializer(listing).data)

    @action(detail=True, methods=["post"])
    def relist(self, request, pk=None):
        """Relist an ended listing."""
        listing = self.get_object()
        from apps.channels.adapters import get_adapter

        try:
            adapter = get_adapter(listing.channel)
            new_id = adapter.relist(listing)
            listing.external_id = new_id
            listing.status = "active"
            listing.last_synced = now()
            listing.save(update_fields=["external_id", "status", "last_synced", "updated_at"])
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ExternalListingSerializer(listing).data)


class ExternalFeedbackViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ExternalFeedbackSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ExternalFeedback.objects.filter(
            listing__channel__workspace=self.request.workspace
        ).select_related("listing")
        channel_id = self.request.query_params.get("channel")
        if channel_id:
            qs = qs.filter(listing__channel_id=channel_id)
        return qs

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        """Record a manual reply to a feedback item."""
        feedback = self.get_object()
        reply_text = request.data.get("reply", "").strip()
        if not reply_text:
            return Response({"detail": "reply is required."}, status=status.HTTP_400_BAD_REQUEST)

        feedback.reply = reply_text
        feedback.replied_at = now()
        feedback.is_replied = True
        feedback.save(update_fields=["reply", "replied_at", "is_replied"])
        return Response(ExternalFeedbackSerializer(feedback).data)


class ExternalQuestionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ExternalQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ExternalQuestion.objects.filter(
            listing__channel__workspace=self.request.workspace
        ).select_related("listing")
        channel_id = self.request.query_params.get("channel")
        if channel_id:
            qs = qs.filter(listing__channel_id=channel_id)
        return qs

    @action(detail=True, methods=["post"])
    def answer(self, request, pk=None):
        """Post an answer to a buyer question."""
        question = self.get_object()
        answer_text = request.data.get("answer", "").strip()
        if not answer_text:
            return Response({"detail": "answer is required."}, status=status.HTTP_400_BAD_REQUEST)

        from apps.channels.adapters import get_adapter

        try:
            adapter = get_adapter(question.listing.channel)
            adapter.post_answer(question, answer_text)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        question.answer_text = answer_text
        question.answer_status = "answered"
        question.answered_at = now()
        question.is_auto_answered = False
        question.save(update_fields=["answer_text", "answer_status", "answered_at", "is_auto_answered"])
        return Response(ExternalQuestionSerializer(question).data)


class ChannelFAQRuleViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelFAQRuleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ChannelFAQRule.objects.filter(
            channel__workspace=self.request.workspace
        ).select_related("channel")
        channel_id = self.request.query_params.get("channel")
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        return qs


class OpenAIAnalyzeView(APIView):
    """
    Requirement analysis endpoint (migrated from nexus extension).
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        text = (request.data.get('text') or request.data.get('prompt') or '').strip()
        if not text:
            return Response(
                {'detail': 'Missing "text" or "prompt" in JSON body.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from apps.channels.services.openai_analysis import analyze_requirements
            payload = analyze_requirements(text)
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(payload)
