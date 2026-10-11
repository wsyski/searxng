---
name: searxng
description: Query the host's SearXNG metasearch instance directly over its JSON API — web, news, science papers, packages and code repos — and diagnose which upstream engines are failing. Search results only; for page content use firecrawl.
disable-model-invocation: true
metadata:
  hermes:
    requires_tools: [__manual_command_only__]
---

# SearXNG

SearXNG runs from `/opt/playground/searxng`, container `searxng-core`, published on
`192.168.1.100:8888`. Firecrawl searches through the same instance via `SEARXNG_ENDPOINT`.

- Endpoint: `${SEARXNG_URL:-http://192.168.1.100:8888}`
- No API key. JSON is enabled; always pass `format=json`.
- Published on the LAN address, not loopback. `localhost:8888` is refused by the host.
- Engine and category counts are not stable. Read them from `sxq --health`, not from here.

## Query

```bash
~/.agents/skills/searxng/scripts/sxq "<query>" [options]
```

```bash
sxq "liferay 7.4 upgrade" -n 5
sxq orlen -e "sii,dna rynkow,ksiazak"
sxq "AI regulation" -c news
sxq --health
```

| Option | Use |
|---|---|
| `-c, --categories` | `general`, `news`, `science`, `it`, `packages`, `repos`, … |
| `-e, --engines` | Pin specific engines instead of a category |
| `--time-range` | `day` \| `week` \| `month` \| `year` |
| `--language` | Result language |
| `--safesearch` | `0` off, `1` moderate, `2` strict |
| `-n, --max-results` | Result count (default 10) |
| `--page`, `--json`, `--health` | Paging, raw JSON, reachability |

Quote multi-word queries: `sxq react hooks` is two arguments and the second is rejected.

For fields `sxq` does not print (`answers`, `infoboxes`, `publishedDate`, raw `score`):

```bash
SX="${SEARXNG_URL:-http://192.168.1.100:8888}"
curl -s -G "$SX/search" --data-urlencode "q=<query>" --data-urlencode format=json \
  | jq '.results[:10][] | {title, url, content, engines}'
```

Always `-G --data-urlencode`, so spaces and `&` survive.

## Always check `.unresponsive_engines`

An empty `.results` **with entries there** means the engines failed or were blocked — not that
the topic has no results. `sxq` prints this notice to stderr on every run; do not suppress it.
It is the single most consequential thing on this page.

`Suspended: …` means the engine asked too fast, **not** that the site blocks this host —
opposite diagnoses, and `references/categories.md` has the table.

## Two behaviours that mislead

- **`--time-range` with `-c news` returns zero** — no error, empty `.unresponsive_engines`.
  `-c general` with `--time-range` works. Take a window and filter on `publishedDate`.
- **A hit does not mean the company is in the title.** Książak reads the WordPress REST API,
  whose `search` matches body text, so `orlen` returns a note about another company.

## When to use this

| Reach for | When |
|---|---|
| `sxq` | Results, titles, snippets, and which engines produced them |
| `/firecrawl` search | Same job, already wired into the stack — prefer it |
| `/firecrawl` scrape, `defuddle` | You have a URL and need the page's text |
| A market-data API | You need a price. Snippets are not numbers |

## References

Read these when the query needs more than a list of results.

- **`references/workflows.md`** — worked examples: analyst coverage by company, recent news,
  code search and PRs, macro queries, packages, and an order of suspicion when results look
  wrong.
- **`references/categories.md`** — every category on this instance with its engine count,
  which ones return nothing and why, and which engines were observed failing.

## Finance news (outside SearXNG)

No finance engine here, and the Google News engine is blocked. Two feeds answer:

```bash
# Google News — `when:2d` limits to the last 2 days (also 1h, 7d)
curl -s -A "Mozilla/5.0" -G https://news.google.com/rss/search \
  --data-urlencode "q=NVDA when:2d" --data-urlencode hl=en-US --data-urlencode gl=US \
  --data-urlencode ceid=US:en -o news.xml
# Yahoo Finance headlines for one or more tickers
curl -s -A "Mozilla/5.0" "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA,AMD&region=US&lang=en-US" -o news.xml

python3 -c "import xml.etree.ElementTree as E
for i in E.parse('news.xml').iter('item'):
    print(i.findtext('pubDate'), '|', i.findtext('source'), '|', i.findtext('title'), '|', i.findtext('link'))"
```

Google News links are redirects; resolve one before scraping it.

## Etiquette

Run queries sequentially. Rapid repeats get upstream engines suspended for everyone on this
instance, Firecrawl included.