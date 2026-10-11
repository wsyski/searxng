# AGENTS.md

SearXNG fork. `upstream` = `searxng/searxng`, `origin` = `wsyski/searxng`.
This repo carries a fork-local deployment layer (`container/`, `postman/`) that
is **not** upstream and is easy to break by merging carelessly.

- `README.md` — short "This fork" summary.
- `DESIGN.md` — repo layout, build system, test infrastructure, toolchain quirks,
  local deployment. **Read it before any task touching tooling, CI, themes, or
  the container.**

## Always

- `./manage` is the build system; `make` is a thin wrapper over it. Never run
  `pip`, `black`, `pylint`, `nose2` or `sphinx` from a bare shell — the toolchain
  is the venv at `local/py3`. Use `./manage <task>` or `./manage pyenv.cmd <cmd>`.
- Tests are **nose2**, not pytest. Single test:
  `./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_query`
  (dotted path only — see `DESIGN.md`, the bare form silently uses the wrong
  settings).
- A green `make test` does **not** mean types were checked; `test.pyright`
  hardcodes `return 0`. See `DESIGN.md`.
- `client/simple/` is built into committed output under `searx/static/`.
  A theme change needs two commits in order: `make static.build.restore` (source),
  then `make static.build.commit` (build products, needs a clean tree).
- Files marked "generated" (`searx/sxng_locales.py`, `searx/data/*.json`,
  `searx/version_frozen.py`) come from `make data.*` / `make docs.prebuild` /
  `python -m searx.version freeze` — never hand-edit them.
- Never commit `container/.env.prod` (gitignored, holds `SEARXNG_SECRET`) or any
  other secret. `container/.env` is committed by design.
- The deployed instance has **no authentication** and is published on the LAN on
  purpose. Do not widen its exposure.
- `AI_POLICY.rst` is enforced by CI: disclose AI assistance, and issue/PR
  descriptions are human-written, not pasted from a model.
- Commits: present tense, imperative, ≤72-char subject. Open an issue before
  large architectural changes.