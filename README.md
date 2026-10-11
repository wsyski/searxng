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

## Agent instructions

- `AGENTS.md` — the short list of rules that apply to every session.
- `DESIGN.md` — repo layout, build system (`./manage`), test infrastructure,
  toolchain quirks, and the local deployment details.

## Housekeeping

`AI_POLICY.rst` (upstream) applies here and is enforced by CI: disclose AI
assistance in contributions, and write issue/PR descriptions yourself rather
than pasting model output.