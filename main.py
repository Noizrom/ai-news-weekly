#!/usr/bin/env python3
"""AI News Weekly — collect → enrich → digest markdown → git archive → static site.

Runs identically locally and in GitHub Actions:
  python main.py              # full run (git commit/push when a remote exists)
  python main.py --dry-run    # collect/enrich/build site only; no git operations
"""
from __future__ import annotations

import argparse
import difflib
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import digest as digest_mod
import enrich as enrich_mod
import sitegen
from sources import collect_all, load_config

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("main")

MIN_ITEMS = 3  # below this, assume an outage rather than publish an empty week


def load_dotenv(path: Path) -> None:
    """Minimal .env loader — never overrides existing environment variables."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


def _title_key(title: str) -> str:
    return "".join(c for c in title.lower() if c.isalnum())[:80]


def dedupe_and_filter(items: list[dict], cfg: dict, seen_urls: set[str]) -> tuple[list[dict], tuple]:
    """Window filter, relevance filter, cross-week exclusion, fuzzy de-duplication."""

    since = datetime.now(timezone.utc) - timedelta(days=int(cfg["window_days"]))
    keywords = [k.lower() for k in cfg.get("community_keyword_filter") or []]
    patterns = [re.compile(rf"\b{re.escape(k)}s?\b") for k in keywords]

    def _is_community(source: str) -> bool:
        return source == "Hacker News" or source.startswith("r/")

    out: list[dict] = []
    kept_titles: list[str] = []
    seen_exact: set[str] = set()
    dropped_undated = dropped_old = dropped_dupes = dropped_offtopic = 0

    for it in items:
        pub = it.get("published")
        if pub is None:
            dropped_undated += 1
            continue
        if pub < since:
            dropped_old += 1
            continue
        title_lower = it["title"].lower()
        if _is_community(it["source"]) and patterns and not any(
            p.search(title_lower) for p in patterns
        ):
            dropped_offtopic += 1
            continue
        url = it["url"]
        if not url or url in seen_urls or url in seen_exact:
            continue
        key = _title_key(it["title"])
        if any(key == _title_key(t) for t in kept_titles):
            dropped_dupes += 1
            continue
        if any(difflib.SequenceMatcher(None, key, t).ratio() >= 0.92 for t in kept_titles):
            dropped_dupes += 1
            continue
        seen_exact.add(url)
        kept_titles.append(key)
        out.append(it)

    return out, (dropped_undated, dropped_old, dropped_dupes, dropped_offtopic)


# ---------------------------------------------------------------- git archive

def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=check
    )


def git_archive(week_id: str) -> None:
    try:
        if _git("rev-parse", "--git-dir", check=False).returncode != 0:
            log.warning("not a git repository — skipping archive")
            return

        identity = _git("config", "user.name", check=False)
        if identity.returncode != 0 or not identity.stdout.strip():
            _git("config", "user.name", "ai-news-bot")
            _git("config", "user.email", "bot@users.noreply.github.com")

        _git("add", "digests")
        if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
            print("git: no digest changes to commit")
        else:
            _git("commit", "-m", f"digest: {week_id}")
            print(f"git: committed {week_id}")

        remotes = _git("remote").stdout.split()
        if "origin" not in remotes:
            log.info("no 'origin' remote — skipping push (local archive only)")
            return
        push = _git("push", "origin", "HEAD", check=False)
        if push.returncode != 0:
            log.warning("push failed (%s); retrying after rebase",
                        push.stderr.strip().splitlines()[-1] if push.stderr else "?")
            _git("pull", "--rebase", "autostash", "origin", "HEAD", check=False)
            push = _git("push", "origin", "HEAD", check=False)
        print("git: pushed to origin" if push.returncode == 0 else f"git: PUSH FAILED: {push.stderr.strip()}")
    except subprocess.CalledProcessError as exc:
        log.error("git %s failed: %s",
                  " ".join(exc.cmd[1:4]), exc.stderr.strip()[:200])


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="collect, enrich, build site; skip all git operations")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    load_dotenv(ROOT / ".env")

    cfg = load_config(ROOT)
    now = datetime.now(timezone.utc)

    raw = collect_all(cfg)
    wid = digest_mod.week_id(now)

    # Cross-week de-duplication: exclude URLs already reported in the most
    # recent PREVIOUS digest (never the current week's own file).
    previous_urls: set[str] = set()
    past = sorted(p for p in (ROOT / "digests").glob("*.md") if p.stem != wid)
    if past:
        previous_urls = digest_mod.extract_urls(past[-1].read_text())
        print(f"excluding {len(previous_urls)} URLs from last digest {past[-1].name}")

    items, (n_undated, n_old, n_dupes, n_offtopic) = dedupe_and_filter(raw, cfg, previous_urls)
    print(f"collected {len(raw)} raw → {len(items)} unique in window "
          f"(dropped: {n_undated} undated, {n_old} out of window, "
          f"{n_dupes} dupes, {n_offtopic} off-topic)")

    if len(items) < MIN_ITEMS:
        log.error("only %d items collected (<%d) — likely a source outage; "
                  "refusing to publish. Run again later.", len(items), MIN_ITEMS)
        return 1

    items, model_used = enrich_mod.enrich(items, cfg)

    digest_path = ROOT / "digests" / f"{wid}.md"
    digest_path.parent.mkdir(exist_ok=True)
    digest_path.write_text(digest_mod.render(items, model_used, now))
    print(f"digest written: digests/{wid}.md ({len(items)} items)")

    weeks_published = sitegen.build(ROOT, cfg)
    print(f"site built: {weeks_published} week(s) → site/index.html")

    if not args.dry_run:
        git_archive(wid)

    top = sorted(items, key=lambda i: -i["importance"])[:5]
    print("\ntop items this week:")
    for i in top:
        print(f"  [{i['importance']}] {i['title']} ({i['source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
