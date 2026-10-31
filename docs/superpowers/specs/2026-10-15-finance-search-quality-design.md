# Finance search quality — design

**Date:** 2026-10-15
**Status:** draft, for review before the plan runs
**Consumers:** the portfolio engine (`/opt/projects/portfolio/main/portfolio`, Idea 4 on the
`portfolio-engineering` kanban board), Firecrawl (`SEARXNG_ENDPOINT`, general search), and the
`searxng` skill's `sxq`.

## Problem

The instance answers finance queries with results that look healthy and are not. Three silent
failures, all measured on the live instance (`192.168.1.100:8888`) on 2026-10-15:

### 1. `sii` matches any single word of a multi-word query

| Query (`engines=sii`) | Results |
|---|---|
| `zzqxv` | 0 |
| `zzqxv qqxzw` | 0 |
| `zzqxv nonsense` | 0 |
| `term` | 10 — *"Czat inwestorski: Photon Energy…"* |
| `zzqxv term` | **10 — the same ten** |
| `recession risk` | 10 — *"Poniedziałkowy przegląd techniczny…", "Nu Holdings…"* |

sii.org.pl's `/szukaj?search=` ORs the terms and matches fragments (`term` → *termin*). The
engine passes every row through. Because `sii` is in `general` (since `e5059452c`), its ten
rows also land in **every** default search — including `ECB interest rate`, where they were 10
of 96 results — and therefore in Firecrawl's search provider. A coverage pass that reads a `sii`
hit as "an analyst wrote about this company" is wrong whenever the query has a second word.

Secondary: `sii.py` and `dna_rynkow.py` interpolate the raw query into the URL
(`f"...?search={query}"`). `ksiazak.py` and `liferay_forum.py` use `urlencode`. A query with
`&`, `#` or `+` (`AT&T`, `C#`) is cut or reinterpreted by the site.

### 2. A time range on news returns zero, silently

```
categories=news, time_range=week, q="ECB interest rate"  →  0 results, unresponsive_engines []
```

All four enabled news engines — `duckduckgo news`, `qwant news`, `wikinews`, `sii` — have
`time_range_support = False`. SearXNG drops such engines when `time_range` is set, so no engine
runs, and an empty, error-free response comes back. The skill already documents the symptom
("recency filtering has to be done client-side"); the cause is configuration, and it is fixable.

`bing news` supports time ranges and was disabled on 2026-10-10 for "connection error". Re-probed
2026-10-15: **10 results without a range, 8 with `time_range=month`**, attributed to `bing news`.
`reuters` still answers `HTTP error`. `mojeek news`, `startpage news` and `yahoo news` are
`inactive` upstream (proof-of-work CAPTCHAs) and cannot be enabled.

> **Re-measured from the host on 2026-10-15: the "connection error" is not bing being down.**
> `bing news` fails here too, on every attempt, with `HTTP connection error`. The cause is the
> transport, not the site. `bing_news.py` sets `enable_http3 = True`, which makes
> `searx/network/client.py` ask for `CurlHttpVersion.V3` — QUIC. UDP/443 is filtered on this
> egress. Measured from inside the container with `curl_cffi`:
>
> | `http_version` | result |
> |---|---|
> | `V3ONLY` | `ConnectionError (56) ngtcp2_conn_writev_stream ERR_DRAINING` |
> | `V3` | the same error |
> | `V2_0` | `200`, 16 110 bytes |
> | `V1_1` | `200`, 16 110 bytes |
>
> So D5 needs one more thing: `enable_http3: false` on the `bing news` entry. That is still a
> settings-only change — `searx/engines/__init__.py` `setattr`s every settings key onto the engine
> module, and `searx/network/network.py` builds that engine's `Network` from the module attribute —
> so no upstream engine file is patched and no new bind-mount is needed. After the change,
> `-c news --time_range=week` returned **4 results, all `bing news`**.

> Re-measured from the host on 2026-10-15, defect 1 confirmed by hand: `?search=zzqxv` gave 0
> blocks (a 404 body), `?search=zzqxv+term` gave 10 and `?search=term` gave 10. The site ORs.

### 3. Pinning an engine that is not loaded silently runs the default search

| `engines=` | Results | Attributed to |
|---|---|---|
| `mojeek news` (inactive) | 96 | `mwmbl` 77, `duckduckgo web` 9, `sii` 10 |
| `startpage news` (inactive) | 97 | same set + `yahoo` |
| `bing news` (disabled, loaded) | 10 | `bing news` 10 |

An unknown or inactive engine name is ignored and the request falls back to the default
categories. A caller who pins one engine and counts results gets someone else's results.
This is upstream behaviour; the fork's own tool, `sxq`, can detect it, because each result
carries its `engines`.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | `sii` keeps a row only when **every query term** appears in its title or teaser, compared case- and diacritic-insensitively (`ł`→`l` handled explicitly; NFKD leaves it alone) | The site's OR semantics cannot be changed. A filter in `response()` is the only place that sees both the query (`resp.search_params["query"]`) and the row. Title+teaser, not the article body, because that is what the engine has. |
| D2 | Single-term queries are filtered the same way | Consistent semantics; a one-word query whose word is absent from title and teaser was a fragment match. |
| D3 | `sii` stays in `[news, general]` | Removing it from `general` would undo the reachability fix of `e5059452c`. With D1 it no longer injects unrelated rows. |
| D4 | `sii` and `dna_rynkow` build URLs with `urlencode` | Same as the two other fork engines. |
| D5 | Enable `bing news` in `core-config/settings.yml`, with `enable_http3: false`, and the probe date and numbers in the comment | The only loaded news engine with `time_range_support`. The `enable_http3` key is the extra half added after re-measuring on 2026-10-15: HTTP/3 over QUIC is blocked on this egress, and that — not bing — was the "connection error". Re-probe rule from the file's header applies. |
| D6 | `sxq` warns when (a) results come from engines that were not pinned, (b) a time range was set and the response is empty with no unresponsive engines | Both are silent failures the tool can name. It does not change results, only stderr. |
| D7 | Postman gets a negative control per defect | `zzqxv term` on `sii` → 0; `-c news` + `time_range=week` → >0 and from `bing news`. The existing `SII: multi-word company name (cd projekt)` asserts every row contains both terms. |

## Non-goals

- Fixing upstream's engine-selection fallback (report it upstream if wanted; human-written issue,
  per `AI_POLICY.rst`).
- A `finance` category — settled in `e5059452c`: no precedent exists, `general` carries it.
- New macro or central-bank engines. Those are RSS feeds; the portfolio reads them directly
  (`rsssafe`), which is the rule in the portfolio's executed Idea 2.
- Re-enabling `reuters`, `google news`, `brave.news`.
- Changing the instance's exposure, port or authentication.

## Risks

- **`bing news` may block again.** The settings comment carries the date; the Postman control
  fails when it does, which is the point.
- **D1 can hide a real result** whose title and teaser use a synonym or abbreviation of a query
  term (`PKN` for `Orlen`). Accepted: a missed hit is visible as a gap; a false hit reads as
  coverage. Ticker-and-name queries are the portfolio's use, and both forms can be issued.
- **The container runs the pinned image.** `sii.py` and `dna_rynkow.py` are bind-mounted; the
  change is inert until `docker restart searxng-core`, and verification is against the
  container, not the repo.
