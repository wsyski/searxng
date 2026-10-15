# Categories on this instance

Measured 2026-10-11 against `192.168.1.100:8888`, SearXNG 2026.10.9. **Single sample per
category** — see "How this was measured" before trusting a row.

**88 of 265 engines are enabled** (re-counted 2026-10-15; the 2026-10-11 figure was 87, before
`bing news` was enabled — see "Changed since 2026-10-11" below).

## Changed since 2026-10-11

The matrix below is the 2026-10-11 sample and is left as measured, so the rows keep their
provenance. These four were re-run on 2026-10-15 because the work that day could have moved them:

| Category | Sample query | 2026-10-11 | 2026-10-15 | Why it moved |
|---|---|---|---|---|
| `news` | kghm | 52, four engines | **53**, five engines | `bing news` enabled; it is the only news engine with `time_range_support` |
| `general` | liferay | 62 | **67** | upstream engine availability, not a config change |
| `science` | crispr | 94 | **85** | as above — a sample, not a property |
| `it` | pytest fixtures | 148 | **151** | as above |

`sii` also changed behaviour rather than count: it now drops any row missing a query term, so it
contributes fewer — and more relevant — rows to `general` than it did on 2026-10-11.

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

| Category | Engines | Returns | Reason |
|---|---|---|---|
| `weather` | 1 | **0** | `wttr.in` fails; it is the only engine |
| `shopping` | 0 | **0** | `geizhals` is the only one, and it fails |
| `currency` | 1 | **0** | `currency_convert` returned nothing |
| `define` | 1 | **0** | single engine returned nothing |
| `translate` | 3 | **0** | no engine answered |

An empty result in any of these means *the engines are not answering*, not that the subject
does not exist. Check `.unresponsive_engines` before concluding anything.

## Engines observed failing

Captured in the same run, and **not** verified individually — these are single observations:

- `yahoo` in `general` — **but it re-tested clean 3/3 when pinned.** Transient.
- `gitlab` in `repos` — reproduced across three queries earlier
- `wttr.in` — in both `weather` and `other`
- 4 of 6 image engines: `bing images`, `brave.images`, `duckduckgo images`, `google cse images`
- 4 of 9 video engines: `bing videos`, `brave.videos`, `google videos`, `vimeo`
- `kickass` (files), `flaticon` (icons), `metacpan` (packages), `openalex` (scientific
  publications), `searchmysite` (blogs), `geizhals` (shopping), `shopify stock` (other)
- `github` — suspended later the same day by over-querying, not failing. See the next section.

`yahoo` is the reason to distrust a one-shot matrix: it appeared broken in one sample and
worked in three pinned queries a minute later. Engine availability here is a **sample**, not a
property.

## Categories that exist but behave oddly

- **`cargo` and `books`** are published categories that **no enabled engine declares**, and
  both still return results — a query falls back rather than coming back empty.
  `/config` does not predict what a category returns.
- **`map`** is the published name, not `maps`.
- **`repos`** shows two engines; `gitlab` fails, so in practice it is GitHub alone.

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
| `mojeek news` (inactive upstream) | 96 | `mwmbl` 77, `duckduckgo web` 9, `sii` 10 |
| `startpage news` (inactive upstream) | 97 | the same set plus `yahoo` |
| `bing news` | 10 | `bing news` 10 |

Nothing in the response says the pin was ignored. `sxq` compares the `engines` on each result
against the pin and warns on stderr when they differ, including under `--json`.

## `--time-range` needs an engine that supports it

Measurements; `SKILL.md` carries the behaviour guidance.

SearXNG **drops** every engine whose `time_range_support` is False when a range is set. In `news`
that was all four of them — `duckduckgo news`, `qwant news`, `wikinews`, `sii` — so `-c news
--time-range week` ran **zero** engines and answered with an empty result and an empty
`.unresponsive_engines`. That is a healthy-looking empty.

`bing news` is enabled and does support ranges; `2026-10-15` it answered 4 results for
`-c news --time-range week`, all attributed to `bing news`. It needs `enable_http3: false` in
`container/core-config/settings.yml`, because `bing_news.py` asks for HTTP/3 and UDP/443 is
filtered on this host. `sxq` warns on stderr when a range is set, the result is empty, and nothing
failed — the signature of that exact configuration.
