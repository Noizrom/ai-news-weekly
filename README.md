# AI News Weekly

A zero-cost, self-updating weekly digest of AI model news. Every Monday morning
it collects announcements from official lab blogs + Hacker News, curates them
with Gemini Flash, publishes a readable page to **GitHub Pages**, commits the
markdown archive to `digests/`, and pushes an **open-link notification** to
your phone via your existing ntfy + MacroDroid setup.

```
collect → enrich → digests/YYYY-Www.md ──commit──► main branch (permanent record)
                        │
                        └─ build site/ ──► GitHub Pages (readable page)
                                              │
                               ntfy open_url ◄┘  phone opens the page
```

## One-time setup (~10 minutes)

1. **Create a public GitHub repo** named e.g. `ai-news-weekly` (public is
   required for free Pages; digests contain only public news) and push:

   ```sh
   git remote add origin git@github.com:<you>/ai-news-weekly.git
   git push -u origin main
   ```

2. **Enable Pages**: repo → Settings → Pages → Source: **GitHub Actions**.

3. **Add repo secrets** (Settings → Secrets and variables → Actions):

   | Secret | Value |
   |---|---|
   | `GEMINI_API_KEY` | Free key from [Google AI Studio](https://aistudio.google.com/apikey) |
   | `NTFY_PHONE_TOPIC` | Your existing topic from `~/.omp/.env` (`NTFY_PHONE_TOPIC`) |
   | `NTFY_PHONE_SERVER` | *(optional)* only if not `https://ntfy.sh` |

4. **Test**: Actions → *weekly-digest* → **Run workflow**. When it finishes,
   your phone gets a notification that opens `<you>.github.io/ai-news-weekly/`.

That's it — it runs itself every Monday 01:00 UTC (09:00 Manila).

## Local use

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py --dry-run   # collect/enrich/build site, no git ops
.venv/bin/python main.py             # full run incl. commit/push
cp .env.example .env                 # optional local secrets
```

## Tuning

Everything lives in `config.yaml`:

- `feeds` — official blog RSS sources (failures are logged and skipped, so a
  dead feed never breaks the digest)
- `hn_queries`, `hn_min_points` — Hacker News coverage via the Algolia API
- `community_keyword_filter` — word-boundary relevance filter for HN/Reddit items
- `ai.models` — Gemini fallback chain (tried in order on rate limits)

Notes:
- Reddit's JSON API blocks datacenter IPs (GitHub runners) most of the time;
  failures are non-fatal by design.
- Without `GEMINI_API_KEY` the digest still generates — items are grouped but
  unclassified/unsummarized.
- Fewer than 3 collected items aborts the run (assumed outage) instead of
  publishing an empty week.
