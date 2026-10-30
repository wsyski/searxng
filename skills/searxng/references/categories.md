# Categories on this instance

Measured 2026-10-11 against `192.168.1.100:8888`, SearXNG 2026.10.9. **Single sample per
category** — see "How this was measured" before trusting a row.

**89 of 265 engines are enabled** (re-counted 2026-10-24 after stooq moved into `finance` and was
enabled; the 2026-10-15 figure was 88 — see "Changed since 2026-10-11" below).

## Changed since 2026-10-11

The matrix below is the 2026-10-11 sample and is left as measured, so the rows keep their
provenance. These four were re-run on 2026-10-15 because the work that day could have moved them:

| Category | Sample query | 2026-10-11 | 2026-10-15 | Why it moved |
|---|---|---|---|---|
| `news` | kghm | 52, four engines | **53**, five engines | `bing news` enabled; it is the only news engine with `time_range_support` |
| `general` | liferay | 62 | **67** | upstream engine availability, not a config change |
| `science` | crispr | 94 | **85** | as above — a sample, not a property |
| `it` | pytest fixtures | 148 | **151** | as above |

`sii` also changed behaviour rather than count: it drops any row missing a query term. It used
to contribute to `general`; since 2026-10-24 it is `finance` only.

## finance and finance-poland (new 2026-10-24)

`sii`, `dna rynkow`, `ksiazak` and `stooq` moved out of `general`/`news` into **both** `finance`
(international/general finance) and `finance-poland` (the Polish subset). They run only when one
of those categories is requested (`-c finance`, `-c finance-poland`, the tabs, or the portfolio
job's explicit `categories=finance-poland` call). Measured 2026-10-24 after stooq was enabled:
`-c finance-poland` + `q=orlen` returned **20 rows**, from `sii`, `ksiazak` and `stooq`;
`dna rynkow` has no Orlen card and returned zero. The `general` and `news` rows in the matrix
above are pre-move — subtract these engines from any post-move count. The earlier `polish-equity`
idea is realized as `finance-poland`: the hyphenated name sorts beside `finance` and works in
`-c`/API/tab, but `!finance-poland` is not a bang (SearXNG rewrites `-` in bangs).

## Opt-in: stooq

`stooq` (`!stq`) is registered in **both** `finance` and `finance-poland` and is **enabled**, so
either category calls it; `-c news` and default general queries do not. It wraps stooq.com's
`/search/`, a PAP **news** index — not ticker lookup, which is `/q/s/` and exact-symbol only. The
site's `robots.txt` allows only Bingbot and Googlebot, and the page is behind a SHA-256
proof-of-work gate and a Google consent wall; the engine clears both. The portfolio requests
`categories=finance-poland` once per day (the scheduled cap); pin it manually with either form:

```bash
sxq orlen -c finance-poland
sxq orlen -e stooq
```

Rows carry a Polish `publishedDate`; a query with no matches is zero results, not an error. Do not
add it to `-c news` — Firecrawl's news searches use that category too.

## What works

| Category | Engines | Sample query | Results |
|---|---|---|---|
| `other` | 12 | x | 641 |
| `stock images` | 7 | workspace | 312 |
| `repos` | 2 | searxng | 239 |
| `packages` | 6 | pydantic | 180 |
| `it` | 17 | pytest fixtures | 148 |
| `icons` | 0 | searxng logo | 127 |
| `videos` | 9 | lofi | 108 |
| `science` | 8 | crispr | 94 |
| `scientific publications` | 5 | transformer | 87 |
| `apps` | 0 | firefox | 88 |
| `general` | 12 | liferay | 62 |
| `q&a` | 3 | pytest fixture | 61 |
| `files` | 5 | linux kernel | 56 |
| `news` | 4 | kghm | 52 |
| `wikimedia` | 40 → 2 | wiki | 40 |
| `blogs` | 0 | searxng | 12 |
| `books` | 0 | dune | 10 |
| `lyrics` | 19 → 1 | hello | 19 |
| `images` | 6 | searxng logo | 19 |
| `software wikis` | 2 | systemd | 16 |
| `social media` | 7 | liferay | 24 |
| `music` | 7 | radiohead | 66 |
| `radio` | 1 | jazz | 9 |
| `dictionaries` | 3 | serendipity | 9 |

## What returns nothing, and why

**Corrected 2026-10-30. The five rows that used to stand here were wrong, and the fault was in
the measuring tool, not the instance.** Answerer-style engines — the `online_currency` and
`online_dictionary` processors, and the weather engines — put their entire output in
**`.answers`**, not `.results`. The probe read `.results` alone, saw an empty array, and four
live categories were written down as dead.

Re-measured 2026-10-30, counting both arrays:

| Category | Query | `.results` | `.answers` | Verdict |
|---|---|---|---|---|
| `weather` | warszawa | 0 | **1** | **live** — `duckduckgo weather` gives a full forecast; `openmeteo` answers too but geocodes "warszawa" to Ohio |
| `currency` | 100 EUR to PLN | 0 | **1** | **live** — `100.0 EUR = 438.85 PLN` |
| `define` | serendipity | 0 | **3** | **live** — `wordnik` |
| `translate` | en-pl dog | 0 | **3** | **live** — `dictzone`, `mymemory translated` |
| `translate` | dog | 0 | 0 | not a fault: the processor needs the `from-to term` form |
| `shopping` | laptop | 0 | 0 | **genuinely dead** — `geizhals` is the only engine and it answers "access denied" |

`sxq` now prints `.answers`, so an answer is no longer reported as "no results". A category
that answers only in `.answers` is normal, not a symptom.

One engine in each of three of these fails, and all three are **deliberately left enabled**
(see `container/core-config/settings.yml`): `wttr.in` (parsing error, in `weather` and `other`),
`mozhi` (HTTP connection error, in `translate`) and `geizhals` (access denied, the sole
`shopping` engine). None of them is in `general`, `news` or any tab, so none costs latency on an
ordinary query — and each one's appearance in `.unresponsive_engines` is the only thing that
separates "this category is broken" from "this category found nothing". Disabling `geizhals`
would make `shopping` answer 0 results with an **empty** `.unresponsive_engines`, which is worse
than the failure it hides.

An empty result in any category still means *check `.unresponsive_engines` first* — and now also
*check `.answers`*.

## Engines observed failing

Captured in the same run, and **not** verified individually — these are single observations:

- `yahoo` in `general` — **but it re-tested clean 3/3 when pinned.** Transient.
- `gitlab` in `repos` — reproduced across three queries earlier. **Since disabled** (2026-10-15),
  so this is history, not something you can reproduce by querying.
- `wttr.in` — in both `weather` and `other`; still failing on 2026-10-30 (parsing error)
- 4 of 6 image engines: `bing images`, `brave.images`, `duckduckgo images`, `google cse images`
- 4 of 9 video engines: `bing videos`, `brave.videos`, `google videos`, `vimeo`
- `kickass` (files), `flaticon` (icons), `metacpan` (packages), `openalex` (scientific
  publications), `searchmysite` (blogs), `geizhals` (shopping, still failing 2026-10-30), `shopify stock` (other)
- `github` — suspended later the same day by over-querying, not failing. See the next section.

`yahoo` is the reason to distrust a one-shot matrix: it appeared broken in one sample and
worked in three pinned queries a minute later. Engine availability here is a **sample**, not a
property.

## Categories that exist but behave oddly

- **`cargo` and `books`** are published categories that **no enabled engine declares**, and
  both still return results — a query falls back rather than coming back empty.
  `/config` does not predict what a category returns.
- **`map`** is the published name, not `maps`.
- **`repos`** shows two enabled engines — `github` and `huggingface`. `gitlab` was observed
  failing earlier and has since been **disabled**, so it is not one of the two; do not re-enable
  it on the strength of the old observation without re-probing.

## A suspension is not a block

`Suspended: access denied` means **this engine asked too fast**, not that the site is blocking
this host. Those are opposite diagnoses with opposite responses — one needs a pause, the other
needs a different egress route — and the message reads like the second.

Observed on `github` on 2026-10-11: roughly 20 engine queries in three minutes produced
`Suspended: access denied` on every subsequent query, while `gh search repos` over the same
terms was unaffected. GitHub's *unauthenticated* search quota is 10 requests a minute.

Measured recovery afterwards, one query every 20 s: probes 1-3 still suspended, probe 4
answered with 30 results. Nothing needed changing — no restart, no config edit. Expect roughly
the documented 180 s window, and allow a margin.

| Message | Window | Usually means |
|---|---|---|
| `Suspended: access denied` | 180 s | too many requests in a short window |
| `Suspended: HTTP error [402, 403]` | 180 s | same window, surfaced as a status |
| `Suspended: too many requests` | 180 s | HTTP 429 from the upstream |
| `Suspended: CAPTCHA` | 3 600 s | the upstream served a challenge |
| `Suspended: CAPTCHA (Cloudflare)` | 15 days | challenged at the edge |
| `Suspended: access denied (Cloudflare)` | 24 h | blocked at the edge |

From `suspended_times` in `searx/settings.yml`.

Before concluding a source is blocked, check whether it was simply asked too much:

```bash
sxq test -e <engine> -n 1     # one query, pinned
sxq --health                 # unrelated engines still answer?
```

If one engine is suspended while the rest of the instance is fine, it is a throttle. If
everything is suspended, it is the network or the instance. If a *different* engine fails after
the same burst, count what you sent in the last minute — `github` and `sii` are both
throttle-prone, at roughly 10 requests a minute unauthenticated and 2-3 in a burst respectively.

## How this was measured

One query per category, single attempt, no retry. That is enough to tell "this works" from
"this is dead", and not enough to certify any individual engine.

To re-measure:

```bash
sxq --health                                   # engine and category counts
sxq "<term>" -c <category>                     # does it answer at all
sxq test -e <engine> -n 1                      # one engine, pinned
```

Pin before blaming an engine. A category query routes across a dozen engines and a single
failure in `.unresponsive_engines` may be noise.

## A pinned engine that is not loaded runs the default search instead

Measurements; `SKILL.md` carries the behaviour guidance.

`engines=mojeek news` — an engine name this instance has never heard of — does **not** return an
error. It returns results from engines nobody asked for, because SearXNG drops the unknown name
from the selection and falls back to the default categories. Measured 2026-10-15:

| `engines=` | Results | Attributed to |
|---|---|---|
| `mojeek news` (inactive upstream) | 96 (2026-10-15) | `mwmbl` 77, `duckduckgo web` 9, `sii` 10 — `sii` is now finance-only, so a repeat is short its rows |
| `startpage news` (inactive upstream) | 97 | the same set plus `yahoo` |
| `bing news` | 10 | `bing news` 10 |

**Fixed fork-side 2026-10-30: the response now says so.** `GET /search?format=json` carries a
`unknown_engines` array alongside `unresponsive_engines`, naming every `engines=` pin this
instance does not have. Re-measured 2026-10-30:

```
engines=mojeek news  ->  36 rows from mwmbl, yahoo, duckduckgo web
                         "unknown_engines": ["mojeek news"]
engines=bing news    ->   9 rows from bing news
                         "unknown_engines": []
```

The *behaviour* is unchanged and deliberately so — the default search still runs in place of an
unknown pin, because that is upstream's semantics and changing it is a separate argument. What
changed is that the response no longer pretends it did what you asked.

`sxq` prefers that field and falls back to comparing each result's `engines` against the pin on
an instance that does not have it (a stock SearXNG), so it still warns either way, on stderr,
including under `--json`.

The server-side change lives in `searx/webadapter.py` (`parse_generic` collects the names it
filters out — they never reach `validate_engineref_list`, which is why upstream could not report
them), `searx/search/models.py` (`SearchQuery.unknown_engines`) and `searx/webutils.py`
(`get_json_response`). All three are bind-mounted into the container; see
`container/docker-compose.override.yml` for why `searx/webapp.py` is not.

## `--time-range` needs an engine that supports it

Measurements; `SKILL.md` carries the behaviour guidance.

SearXNG **drops** every engine whose `time_range_support` is False when a range is set. In `news`
that is `duckduckgo news`, `qwant news` and `wikinews`; only `bing news` remains.

**Re-measured 2026-10-30, q=kghm — this supersedes the 2026-10-24 reading below:**

| probe | rows | engines | unresponsive |
|---|---|---|---|
| `-c news` (no range) | 34 | `duckduckgo news` 27, `bing news` 9, `wikinews` 5 | `qwant news`: access denied |
| `-c news --time-range day` | 4 | `bing news` 4 | `qwant news` suspended |
| `-c news --time-range week` | 7 | `bing news` 7 | `qwant news` suspended |
| `-c news --time-range month` | 8 | `bing news` 8 | `qwant news` suspended |
| `-e "bing news"` (no range) | 9 | `bing news` 9 | — |

`bing news` is **healthy**, and `-c news --time-range` runs it and returns rows.

The 2026-10-24 reading recorded here — *zero* rows at `day` and `week`, with `bing news`
answering a parsing error on an empty response body — **does not reproduce**. It contradicted the
2026-10-15 note in `container/core-config/settings.yml` (10 unranged / 5 month / 3 week), and the
2026-10-30 set agrees with that note in kind. Read the 10-24 figure as a transient upstream blip,
not as the state of this instance; it is kept named here only so nobody re-derives it from an old
copy of this file.

The portfolio's Firecrawl news sweeps still omit `tbs`. That is a decision on the portfolio side
and is not changed by this measurement — but the reason given for it no longer holds.

`bing news` needs `enable_http3: false` in `container/core-config/settings.yml`, because
`bing_news.py` asks for HTTP/3 and UDP/443 is filtered on this host. `sxq` warns on stderr when a
range is set, the result is empty, and nothing
failed — the signature of that exact configuration.
