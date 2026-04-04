#!/usr/bin/env python3
"""Copy template trees and replace placeholders."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PLACEHOLDERS = (
    "__APP_SLUG__",
    "__APP_TITLE__",
    "__APP_MODULE__",
    "__APP_CONFIG_CLASS__",
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("src", type=Path, help="Template root (e.g. templates/server)")
    p.add_argument("dst", type=Path, help="Destination directory")
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    args = p.parse_args()

    mapping = {
        "__APP_SLUG__": args.slug,
        "__APP_TITLE__": args.title,
        "__APP_MODULE__": f"apps.{args.slug}",
        "__APP_CONFIG_CLASS__": _config_class(args.slug),
    }

    if not args.src.is_dir():
        print(f"Missing template dir: {args.src}", file=sys.stderr)
        return 1

    if args.dst.exists():
        shutil.rmtree(args.dst)
    args.dst.mkdir(parents=True, exist_ok=True)

    for path in args.src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(args.src)
        out = args.dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_text(encoding="utf-8")
        for k, v in mapping.items():
            data = data.replace(k, v)
        out.write_text(data, encoding="utf-8")

    return 0


def _config_class(slug: str) -> str:
    parts = [x for x in slug.replace("-", "_").split("_") if x]
    pascal = "".join(x[:1].upper() + x[1:].lower() for x in parts)
    return f"{pascal}Config"


if __name__ == "__main__":
    raise SystemExit(main())
