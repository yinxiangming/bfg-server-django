# -*- coding: utf-8 -*-
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from __APP_MODULE__.services.openai_analysis import analyze_requirements


class OpenAIAnalyzeView(APIView):
    """
    Minimal requirement analysis endpoint. Tighten permissions for production.
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
            payload = analyze_requirements(text)
        except Exception as exc:  # noqa: BLE001
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(payload)
