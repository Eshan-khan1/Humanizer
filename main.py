#!/usr/bin/env python3
"""Humanize — PyWebView native desktop shell for macOS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

from app_backend import HumanizeAPI

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
INDEX_HTML = WEB_DIR / "index.html"


def main() -> None:
    if not INDEX_HTML.is_file():
        print(f"Missing UI file: {INDEX_HTML}", file=sys.stderr)
        sys.exit(1)

    os.environ.setdefault("NLTK_DATA", str(ROOT / "nltk_data"))

    api = HumanizeAPI()
    url = INDEX_HTML.as_uri()

    print(f"Python:   {sys.executable}")
    print(f"UI:       {INDEX_HTML}")
    print("Starting Humanize (PyWebView)…")

    webview.create_window(
        title="Humanize",
        url=url,
        js_api=api,
        width=1100,
        height=720,
        min_size=(920, 640),
        background_color="#f3f4f6",
        text_select=True,
    )

    # Native WebKit window on macOS (coco)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
