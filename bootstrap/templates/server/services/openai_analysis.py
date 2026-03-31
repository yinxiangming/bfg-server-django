# -*- coding: utf-8 -*-
"""
Simple OpenAI-backed requirement analysis. Extend pipeline for richer tasks later.
"""
from __future__ import annotations

import os
from typing import Any

from __APP_MODULE__.services import pipeline


def analyze_requirements(user_text: str) -> dict[str, Any]:
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        return {
            'enabled': False,
            'message': 'OPENAI_API_KEY is not configured.',
            'stages': [s.name for s in pipeline.PIPELINE_STAGES],
            'placeholder_tasks': pipeline.build_placeholder_tasks(user_text),
        }

    model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini').strip()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError('openai package is not installed.') from exc

    client = OpenAI(api_key=key)
    system = (
        'You are a concise product analyst for BFG (Django + DRF backend, Next.js admin). '
        'Respond with short bullet sections: Summary, Entities, API/admin ideas, Risks.'
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_text},
        ],
        temperature=0.2,
    )
    content = (resp.choices[0].message.content or '').strip()
    return {
        'enabled': True,
        'model': model,
        'analysis': content,
        'stages': [s.name for s in pipeline.PIPELINE_STAGES],
        'placeholder_tasks': pipeline.build_placeholder_tasks(user_text),
    }
