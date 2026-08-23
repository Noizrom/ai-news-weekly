"""Collectors for official blog RSS/Atom feeds, Hacker News, and Reddit.

Every collector returns a list of normalised item dicts; failures are logged
and returned empty so one dead source never kills the weekly digest.
"""
from __future__ import annotations

import calendar
import html
import logging
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yaml

log = logging.getLogger("sources")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ai-news-weekly/1.0; personal digest)",
}


def load_config(root) -> dict:
    return yaml.safe_load((root / "config.yaml").read_text())


def _item(title: str, url: str, source: str, published: datetime | None) -> dict:
    return {
        # Escape early: titles flow into markdown/HTML unmodified later.
        "title": html.escape((title or "").strip(), quote=False),
        "url": (url or "").split("#")[0].strip(),
        "source": source,
        "published": published,
    }


def fetch_feed(name: str, url: str, limit: int) -> list[dict]:
    parsed = feedparser.parse(url, request_headers=HEADERS)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"feed error: {parsed.bozo_exception}")
    items = []
    for e in parsed.entries[:limit]:
        published = None
        for key in ("published_parsed", "updated_parsed"):
            st = getattr(e, key, None)
            if st:
                published = datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
                break
        items.append(_item(e.get("title", ""), e.get("link", ""), name, published))
    return items


def fetch_hn(cfg: dict, since: datetime) -> list[dict]:
    """Hacker News via the Algolia search-by-date API."""
    since_ts = int(since.timestamp())
    min_points = int(cfg.get("hn_min_points", 40))
    seen, items = set(), []

    for query in cfg.get("hn_queries", []):
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={
                    "query": query,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{since_ts},points>{min_points}",
                    "hitsPerPage": 50,
                },
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                oid = hit.get("objectID")
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                published = datetime.fromtimestamp(
                    hit.get("created_at_i", 0), tz=timezone.utc
                )
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={oid}"
                items.append(_item(hit.get("title", ""), url, "Hacker News", published))
        except Exception as exc:  # noqa: BLE001 — one failed query must not kill the rest
            log.warning("HN query %r failed: %s", query, exc)

    return items


def fetch_reddit(cfg: dict, since: datetime) -> list[dict]:
    items = []
    min_score = int(cfg.get("reddit_min_score", 25))

    for sub in cfg.get("subreddits", []):
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/top.json",
                params={"t": "week", "limit": 50},
                headers={"User-Agent": HEADERS["User-Agent"]},
                timeout=20,
            )
            resp.raise_for_status()
            for child in resp.json().get("data", {}).get("children", []):
                post = child.get("data", {})
                created = datetime.fromtimestamp(
                    post.get("created_utc", 0), tz=timezone.utc
                )
                title = post.get("title", "")
                if post.get("score", 0) < min_score or created < since:
                    continue
                items.append(
                    _item(
                        title,
                        f"https://reddit.com{post.get('permalink', '')}",
                        f"r/{sub}",
                        created,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("Reddit r/%s failed: %s", sub, exc)

    return items


def collect_all(cfg: dict) -> list[dict]:
    """Run every configured source; return raw collected items."""
    since = datetime.now(timezone.utc) - timedelta(days=int(cfg["window_days"]))
    max_per_source = int(cfg.get("max_items_per_source", 40))

    items: list[dict] = []
    for feed in cfg.get("feeds", []):
        try:
            got = fetch_feed(feed["name"], feed["url"], max_per_source)
            log.info("[feed] %-16s %d items", feed["name"], len(got))
            items.extend(got)
        except Exception as exc:  # noqa: BLE001
            log.warning("[feed] %-16s FAILED: %s", feed["name"], exc)

    hn = fetch_hn(cfg, since)
    log.info("[hn] %d items", len(hn))
    items.extend(hn)

    rd = fetch_reddit(cfg, since)
    log.info("[reddit] %d items", len(rd))
    items.extend(rd)

    return items
