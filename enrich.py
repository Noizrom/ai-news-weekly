"""Batched LLM enrichment via the Gemini REST API with model fallback.

Without GEMINI_API_KEY the pipeline degrades gracefully: items keep default
categories/importance and the digest + site are still produced and archived.
"""
from __future__ import annotations

import json
import logging
import os
import time

import requests

log = logging.getLogger("enrich")

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
CATEGORIES = ("frontier_release", "open_weights", "research", "industry", "other")

PROMPT_TEMPLATE = """You are curating a weekly AI-news digest. Classify each item below.

Return STRICT JSON only: {{"analyses": [{{"i": <item number>, "category":
"frontier_release"|"open_weights"|"research"|"industry"|"other", "importance":
<1-5>, "summary": "<one informative sentence>"}}]}} — one analysis per item,
same order. importance: 5=major frontier/open-weight release, 4=significant,
3=notable, 2=minor, 1=noise. The summary states WHAT was released/announced
and the concrete capability or fact. Never invent facts not implied by the
title/source.

Items:
{items}
"""


def enrich(items: list[dict], cfg: dict) -> tuple[list[dict], str]:
    """Attach category/importance/summary to each item. Returns (items, model_used)."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    ai_cfg = cfg.get("ai", {})
    models = ai_cfg.get("models", ["gemini-2.5-flash-lite"])
    batch_size = int(ai_cfg.get("batch_size", 12))
    rate_limit = float(ai_cfg.get("rate_limit_seconds", 4))

    for item in items:
        item.setdefault("category", "other")
        item.setdefault("importance", 3)
        item.setdefault("summary", "")

    if not ai_cfg.get("enabled", True) or not api_key:
        log.warning("GEMINI_API_KEY not set — skipping AI enrichment (fallback layout)")
        return items, ""

    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]
    used_model = ""
    for bi, batch in enumerate(batches, 1):
        listing = "\n".join(
            f"{n}. [{it['source']}] {it['title']}" for n, it in enumerate(batch, 1)
        )
        analyses, model_used = _generate(
            PROMPT_TEMPLATE.format(items=listing), api_key, models, rate_limit
        )
        if model_used:
            used_model = model_used
        if not analyses:
            log.warning("batch %d/%d: no AI response, keeping defaults", bi, len(batches))
            continue
        by_index = {a.get("i"): a for a in analyses if isinstance(a, dict)}
        for n, item in enumerate(batch, 1):
            a = by_index.get(n) or by_index.get(str(n)) or {}
            category = a.get("category", "other")
            item["category"] = category if category in CATEGORIES else "other"
            try:
                item["importance"] = max(1, min(5, int(a.get("importance", 3))))
            except (TypeError, ValueError):
                item["importance"] = 3
            item["summary"] = str(a.get("summary", "")).strip()
        log.info("batch %d/%d enriched (%d items)", bi, len(batches), len(batch))

    return items, used_model


def _generate(prompt: str, api_key: str, models: list[str], rate_limit: float):
    """Call Gemini with a fallback chain. Returns (analyses_list, model_name_or_'')."""
    for attempt, model in enumerate(models):
        if attempt:
            time.sleep(rate_limit)
        try:
            resp = requests.post(
                f"{API_BASE}/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.3,
                        "maxOutputTokens": 4096,
                    },
                },
                timeout=60,
            )
            if resp.status_code in (429, 500, 503):
                log.warning("%s unavailable (%d), trying next model", model, resp.status_code)
                continue
            if resp.status_code != 200:
                log.warning("%s HTTP %d: %s", model, resp.status_code, resp.text[:200])
                continue
            text = (
                resp.json()
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            ).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
            data = json.loads(text)
            analyses = data.get("analyses", [])
            if isinstance(analyses, list):
                return analyses, model
        except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError) as exc:
            log.warning("%s call failed: %s", model, exc)
    return [], ""
