"""Markdown rendering of the weekly digest."""
from __future__ import annotations

from datetime import datetime, timezone

SECTION_ORDER = [
    ("frontier_release", "Frontier releases"),
    ("open_weights", "Open weights & models"),
    ("research", "Research & papers"),
    ("industry", "Industry & business"),
    ("other", "Other notable"),
]


def week_id(now: datetime | None = None) -> str:
    iso = (now or datetime.now(timezone.utc)).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def render(items: list[dict], model_used: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    wid = week_id(now)
    since = now - __import__("datetime").timedelta(days=7)
    fmt = "%b %d"
    ranges = (
        f"{since.strftime(fmt)} – {(now - __import__('datetime').timedelta(days=1)).strftime('%b %d, %Y')}"
    )

    lines = [
        f"# AI News Weekly — {wid}",
        "",
        f"*{ranges} · {len(items)} items"
        + (f" · curated by {model_used}" if model_used else " · uncurated (no API key)") +
        "*",
        "",
    ]

    ranked = sorted(items, key=lambda i: (-i["importance"], i["source"]))
    tldr = [i for i in ranked if i["importance"] >= 4][:8]
    if tldr:
        lines += ["## TL;DR", ""]
        lines += [f"- **[{i['title']}]({i['url']})** — {i['source']}" for i in tldr]
        lines.append("")

    for cat, heading in SECTION_ORDER:
        bucket = sorted(
            (i for i in items if i["category"] == cat),
            key=lambda i: (-i["importance"], i["source"]),
        )
        if not bucket:
            continue
        lines += [f"## {heading}", ""]
        for i in bucket:
            summary = f" — {i['summary']}" if i["summary"] else ""
            lines.append(f"- **[{i['title']}]({i['url']})**{summary} *({i['source']})*")
        lines.append("")

    if len(lines) <= 7:  # header only → genuinely quiet week
        lines += ["No notable AI news collected this week.", ""]

    return "\n".join(lines)


def extract_urls(markdown: str) -> set[str]:
    """All http(s) URLs referenced in a digest — used for cross-week de-duplication."""
    import re

    return set(re.findall(r"https?://[^\s\)\]]+", markdown))
