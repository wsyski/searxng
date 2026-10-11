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
itself — one file, not the `engines/` directory, so the image's other 253 stay
untouched:

```yaml
- ../searx/engines/liferay_forum.py:/usr/local/searxng/searx/engines/liferay_forum.py:ro
```

Drop that line once the engine is upstream or the pin moves past it. Register the
engine in `container/core-config/settings.yml`, where `use_default_settings:
true` appends names it does not already know.

`liferay forum` (module `searx/engines/liferay_forum.py`, shortcut `!lf`) is the
only one so far. It queries the Discourse instance at `discuss.lifecycle.com`,
whose `search.json` returns JSON over plain HTTP and whose robots.txt allows
`User-agent: *`. Two behaviours to know before writing the next one:

- **Discourse rate-limits anonymous clients hard.** A burst earns a 180 s
  suspension, surfaced by SearXNG as `Suspended: too many requests` in
  `unresponsive_engines` — not as an empty result. Search one at a time.
- **A quoted query with no matches returns no `topics` key at all**, so the
  result is empty rather than an error. Discourse also ANDs the terms, so
  multi-word phrases often legitimately have no hits.

`paging` is off: `/search.json` accepts `page` but returns the same set for
page 0 and page 1.

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