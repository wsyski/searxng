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

- Endpoint: `${SEARXNG_ENDPOINT:-${SEARXNG_URL:-http://192.168.1.100:8888}}` — prefer
  `SEARXNG_ENDPOINT`: `SEARXNG_URL` is a registered Hermes tool variable, so Hermes strips it from
  a terminal, `execute_code` or cron child and the fallback address is used without a word. `sxq`
  names which of the three it used.
- No API key. JSON is enabled; always pass `format=json`.
- Published on the LAN address, not loopback. `localhost:8888` is refused by the host.
- Engine and category counts are not stable. Read them from `sxq --health`, not from here.

## Query

```bash
~/.agents/skills/searxng/scripts/sxq "<query>" [options]
```

```bash
sxq "liferay 7.4 upgrade" -n 5
sxq orlen -c finance-poland
sxq granges -c finance-sweden
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

`sxq` prints `.answers` as well as `.results`, with a leading `=`. Some categories answer only
there — `weather`, `currency`, `define` and `translate` put their whole output in `.answers` and
never fill `.results`, which is why they were once mistaken for dead categories. `translate`
needs the `from-to term` form: `sxq "en-pl dog" -c translate`, not a bare word.

For fields `sxq` does not print (`infoboxes`, `publishedDate`, raw `score`):

```bash
SX="${SEARXNG_ENDPOINT:-${SEARXNG_URL:-http://192.168.1.100:8888}}"
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

`sxq` writes three further diagnostics to **stderr**, including under `--json`, so stdout stays a
clean document and `sxq … --json | jq` keeps working: one when a pin was ignored, one when a
`--time-range` came back empty with nothing failing, one when an engine reported something about
its own response (today only `sii`'s drop count). All three are described below. Do not silence
stderr on a pinned or ranged query — it is the only place any of those failures is visible.

## Four behaviours that mislead

- **`--time-range` with `-c news` runs exactly one engine.** Only `bing news` has
  `time_range_support`; the other three are dropped when a range is set, so a range narrows the
  category to a single source. Re-measured 2026-10-30, q=kghm: 4 rows at `day`, 7 at `week`, 8 at
  `month`, all `bing news`, against 34 rows unranged from three engines. It **works** — an earlier
  2026-10-24 reading of zero rows and a `bing news` parsing error does not reproduce. The cost is
  breadth, not correctness: a ranged `-c news` is `bing news` alone, so take a window and filter on
  `publishedDate` when you want all four sources.
- **A hit does not mean the company is in the title.** Książak reads the WordPress REST API,
  whose `search` matches body text, so `orlen` returns a note about another company.
- **A `sii` hit carries every query term.** sii.org.pl ORs the terms, so `zzqxv term` returns the
  same ten rows as `term`; the engine drops any row missing a term (measured 2026-10-15, where
  those ten rows were 10 of 96 in a general search; `sii` now runs only in `finance`). A `sii` result therefore names its company —
  but a *miss* can still be a synonym (`PKN` for `Orlen`), so issue the ticker and the name. The
  engine publishes the count in the response: `engine_data.sii.dropped_rows` and `.site_rows`,
  on every `sii` response including a zero one, so `engine_data.sii` being present is itself the
  statement "sii ran". `sxq` prints a stderr warning when the count is non-zero. An empty `sii`
  result is not proof that sii.org.pl has nothing — check the count before concluding it.
- **The Swedish subset is `finance-sweden`, and it filters the same way.** `aktienyheterna`
  (`!akn`, the WordPress REST API) and `placera` (`!pla`, Avanza's editorial site, archive back to
  2006) are in `finance` and `finance-sweden`; the two Avanza books ask for the subset once a day.
  Both sites rank near-misses into their own result page, so both engines keep a row only when
  every query term is a whole word in what they can see of it, and both publish
  `engine_data.<name>.dropped_rows` / `.site_rows` on every response. `granges` is the query that
  shows why: placera ranks in press releases about *grants* and board *changes*, and
  aktienyheterna's `search=granges` returns two Spendrups posts naming **Grängesberg** — a town,
  not the company. Unfiltered, "has anyone written about Gränges" is answered "yes, twice". So
  read `site_rows` before reading an empty answer as a broken engine.
  `finance` is now the **union** of both markets, not a synonym for the Polish set.
- **A pinned engine that is not loaded runs the default search, and the API
  reports nothing wrong.** `engines=mojeek news` returns default-category rows from
  `mwmbl` and `duckduckgo web` — a caller who pins one engine and counts
  results gets someone else's. **The response now names the pin** — `unknown_engines` in the JSON,
  alongside `unresponsive_engines` (fork-side, 2026-10-30). The fallback behaviour is unchanged:
  the default search still runs. `sxq` reports that field, and still infers the same thing from
  the per-row `engines` on a stock instance that lacks it. See `references/categories.md`.
- **A category this instance does not have does the same thing, and louder.** An unknown
  `categories=` name selects no engine, so the DEFAULT search runs: `-c finance-polnd` (a
  misspelt `finance-poland`) answered 36 rows from `mwmbl`, `duckduckgo web` and `yahoo`, and
  `unknown_engines` was empty because no *engine* was pinned. **The response now names it** —
  `unknown_categories` in the JSON (fork-side, 2026-10-30). `sxq` reports it on stderr, under
  `--json` too.

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

## Per-ticker headlines (outside SearXNG)

`-c news --time-range` works now (above), but it searches *headlines*, not per-ticker feeds. For
"what happened to NVDA today" these two RSS endpoints remain the direct route.

Name collision worth stating once: SearXNG's `google news` **engine** is disabled here ("access
denied"), which has nothing to do with the Google News **RSS** endpoint below, which answers.

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
