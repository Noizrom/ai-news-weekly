"""Publish an open_url envelope to ntfy — same contract as the phone skill's publisher.

The topic is a bearer secret: it is only ever read from the environment
(NTFY_TOPIC / NTFY_SERVER, or GH Actions secrets) and never printed.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from urllib.parse import urlparse

import requests


def build_envelope(url: str) -> dict:
    p = urlparse(url)
    if p.scheme != "https:" or not p.netloc:
        raise ValueError(f"refusing to publish non-https URL: {p.scheme or 'no scheme'}")
    if p.username or p.password or "@" in p.netloc:
        raise ValueError("refusing to publish URL with embedded credentials")
    return {"v": 1, "id": str(uuid.uuid4()), "op": "open_url", "url": url}


def send(url: str, server: str | None = None, topic: str | None = None) -> None:
    server = (server or os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    topic = topic or os.environ.get("NTFY_TOPIC") or ""
    if not topic:
        raise SystemExit("NTFY_TOPIC is not set (env var or argument)")
    resp = requests.post(
        f"{server}/{topic}",
        data=json.dumps(build_envelope(url)).encode(),
        headers={"Content-Type": "application/json", "Title": "AI News Weekly"},
        timeout=20,
    )
    resp.raise_for_status()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: notify.py <public-digest-url>")
    send(sys.argv[1])
    print("notification sent")
