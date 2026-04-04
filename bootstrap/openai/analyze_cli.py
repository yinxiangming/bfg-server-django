#!/usr/bin/env python3
"""
CLI helper to test OpenAI analysis outside Django (optional).

Usage:
  OPENAI_API_KEY=... python analyze_cli.py "Describe the feature"
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?", default="")
    args = parser.parse_args()
    text = args.prompt.strip() or sys.stdin.read().strip()
    if not text:
        print("No prompt provided.", file=sys.stderr)
        return 2
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1
    try:
        from openai import OpenAI
    except ImportError:
        print("openai package not installed.", file=sys.stderr)
        return 1
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a concise product analyst for a BFG/Django + Next.js extension.",
            },
            {"role": "user", "content": text},
        ],
        temperature=0.2,
    )
    print(resp.choices[0].message.content or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
