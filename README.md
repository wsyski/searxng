# This fork

`wsyski/searxng` tracks `searxng/searxng` (the `upstream` remote). Upstream
code is unmodified in intent; what follows is the delta.

## Local deployment layer

`container/` and `postman/` are fork-local and have no upstream equivalent.

- The instance is deployed with docker compose from `container/docker-compose.yml`
  plus `container/docker-compose.override.yml`. Keeping our settings in the
  *override* file (rather than editing the base file) means upstream changes to
  the compose file merge cleanly.
- `container/core-config/settings.yml` is bind-mounted over `/etc/searxng` and is
  the effective runtime config. It enables `search.formats: [html, json]`
  because the **Firecrawl** instance at `/opt/playground/firecrawl` uses this
  SearXNG as its search provider (`GET /search?q=...&format=json`).
- Its engine list records, per engine, whether it answers from this egress IP as
  of the probe date. Engines that CAPTCHA or rate-limit us are disabled. Re-probe
  before re-enabling one — the verdict is IP-specific and time-sensitive.
- `postman/run.sh` (newman) is the integration smoke test for a running
  instance; use it after any config or image change.

## Two ways this instance answers, and looks fine

Both were live defects on 2026-10-15 and both are fixed; they are written down
because a *client* cannot tell the difference from a correct answer, and
Firecrawl searches through this instance.

- **A news query with a time range runs exactly one engine.** SearXNG *drops*
  every news engine without `time_range_support`, and only `bing news` has it.
  Re-measured 2026-10-30, `q=kghm`: 4 rows at `day`, 7 at `week`, 8 at `month`,
  all `bing news`, against 34 rows unranged from three engines. It **works** — an
  earlier 2026-10-24 reading of zero rows and a `bing news` parsing error does
  not reproduce. `bing news` keeps `enable_http3: false` because `bing_news.py`
  asks for HTTP/3 and UDP/443 is filtered on this egress. The cost of a range is
  breadth, not correctness: it narrows `news` to one source, so take a window and
  filter on `publishedDate` when you want all four.
- **Pinning an engine this instance does not have runs the default search.**
  `engines=mojeek news` returned 96 rows from `mwmbl`, `duckduckgo web` and
  `sii` when it was measured on 2026-10-15; `sii` is finance-only since
  2026-10-24, so a repeat would be short those rows. That is upstream behaviour
  **The response says so since 2026-10-30:** `unknown_engines`, alongside
  `unresponsive_engines`, in `GET /search?format=json`. The fallback behaviour is
  unchanged — the default search still runs — but it is no longer silent. The
  skill's `sxq` reports that field and keeps its own inference for a stock
  instance that lacks it. `DESIGN.md` → Local deployment has the measurements.

**This instance has no authentication.** It is published on the LAN address so
LAN clients can reach it, which makes it an open search proxy. Keep it that way
and no wider.

`container/.env.prod` holds `SEARXNG_SECRET` and is gitignored. It is not a
credential between Firecrawl and this instance — there is no authentication at
all — but SearXNG **refuses to boot** with the default `secret_key`: with
`debug: false`, `searx/webapp.py` logs `server.secret_key is not changed` and
exits. Verified by running the pinned image without it. The secret also keys the
results cache and the preferences cookie, so losing it invalidates both.

## Fork-local engines

A new engine in `searx/engines/` is invisible to the container while the image
is pinned. `docker-compose.override.yml` therefore bind-mounts the engine file
itself — one file, not the `engines/` directory, so the image's other engines
stay untouched:

```yaml
- ../searx/engines/liferay_forum.py:/usr/local/searxng/searx/engines/liferay_forum.py:ro
```

Drop that line once the engine is upstream or the pin moves past it. Register the
engine in `container/core-config/settings.yml`, where `use_default_settings:
true` appends names it does not already know.

`liferay forum` (module `searx/engines/liferay_forum.py`, shortcut `!lf`)
queries the Discourse instance at `discuss.lifecycle.com`, whose
`search.json` returns JSON over plain HTTP and whose robots.txt allows
`User-agent: *`. Three behaviours to know before writing the next one:

- **Discourse rate-limits anonymous clients hard.** A burst earns a 180 s
  suspension, surfaced by SearXNG as `Suspended: too many requests` in
  `unresponsive_engines` — not as an empty result. Search one at a time.
- **A quoted query with no matches returns no `topics` key at all**, so the
  result is empty rather than an error. Discourse also ANDs the terms, so
  multi-word phrases often legitimately have no hits.
- **`paging` is off**: `/search.json` accepts `page` but returns the same set for
  page 0 and page 1.

The other three fork-local engines are finance sources, and the trap each one
documents in its own module docstring is a *measurement*, so read that before
changing anything:

| Engine | Source | What bit us |
|---|---|---|
| `sii` (`!sii`) | sii.org.pl `/szukaj` | The parameter is `search`, **not `q`** — `?q=` answers 200 with one identical 62 kB page for every query including a nonsense one, so a wrong parameter reads as a healthy engine that found nothing. A zero-hit query is **404**, not an empty 200. And the site **ORs** the terms and matches fragments, so `zzqxv term` returned the same ten rows as `term`; the engine now keeps a row only when every query term appears in its title or teaser. |
| `dna rynkow` (`!dna`) | dnarynkow.pl `/spolki/?search=` | No search *page* — only a parameter, so every path-shaped probe 404s while the search works. Results are server-rendered into the HTML body, not into the `__NUXT_DATA__` payload. |
| `ksiazak` (`!ksz`) | konradksiazak.pl WordPress REST | `search` matches body text, so a hit does **not** mean the company is in the title. |

These three, and stooq below, are in **both `finance` and `finance-poland`** —
not `general` or `news`. `finance` is the international/general finance category;
`finance-poland` is the Polish subset. A default search no longer runs them;
request either category explicitly (`-c finance` / `-c finance-poland` or the
tabs). The portfolio's DeGiro news pass asks for `finance-poland` once per day
for the highest-weight uncovered holding.

The fifth fork-local engine is not a company source. `stooq` (`!stq`) wraps
stooq.com's `/search/`, which is a Polish **news** index of PAP items, not a
ticker lookup (`/q/s/` matches symbols only). It is **enabled in
`finance`/`finance-poland` only**, so it never joins ordinary news/general searches —
including Firecrawl's — and runs when that category is requested. The portfolio
requests it once per day; a manual `-c finance` is an explicit request. That is
deliberate: the site's `robots.txt` allows only Bingbot and Googlebot, and the
page sits behind a SHA-256 proof-of-work gate plus a Google consent wall, both of
which the engine clears. `searx/engines/stooq.py` records the measurement.

Sixth mount is not fork-local: `github.py` is an **upstream** engine patched
here to read the GitHub token from the environment. Without that mount the
container keeps the image's copy and the patch is a silent no-op — the repo
looks patched while nothing changed.

`sii` and `dna rynkow` are rate-limit-prone (`sii` answers 429 after two or
three searches in a burst and is then suspended for an hour). Keep Postman runs
to the sii folder or space the requests out.

## Choosing what a client may ask for

An empty `categories=` is read as *unspecified*, and the instance falls back to
`general` — it does not mean "match nothing" and it does not mean "all
categories". A category with no enabled engines returns HTTP 200, zero results
and an **empty** `unresponsive_engines`, so there is no error to notice.

The engine list is published by `/config`. Read that rather than
`searx/settings.yml` in this repo: the running instance merges the defaults
bundled in its pinned image, not this working tree.

## Agent instructions

- `AGENTS.md` — the short list of rules that apply to every session.
- `DESIGN.md` — repo layout, build system (`./manage`), test infrastructure,
  toolchain quirks, and the local deployment details.

Bare requests against the instance live in `postman/` here and nowhere else.
Anything that goes *through* Firecrawl — the `/v2/search` mappers, and the
external sources that render client-side and so cannot be SearXNG engines —
belongs in the firecrawl project's collection.

## Housekeeping

`AI_POLICY.rst` (upstream) applies here and is enforced by CI: disclose AI
assistance in contributions, and write issue/PR descriptions yourself rather
than pasting model output.
