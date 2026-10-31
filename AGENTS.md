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
  The venv is on `PATH` **by absolute path**, so a resolved `python` does not
  warn about `sys.prefix`; keep it that way if you touch `utils/lib.sh`.
- Tests are **nose2**, not pytest. Single test:
  `./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_query`
  (dotted path only — see `DESIGN.md`, the bare form silently uses the wrong
  settings).
- A green `make test` does **not** mean types were checked across the tree;
  `test.pyright` still discards its result. The `test.pyright_modified` step
  that `make test` actually runs *does* gate, at error level, on locally
  modified files only. See `DESIGN.md`.
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
- **The `searxng` skill is authored here**, in `skills/searxng/`, and mirrored into
  the user hub at `~/.agents/skills/searxng` so three harnesses can load it.
  After editing it, run `make skill.sync` — without that the hub keeps serving
  the old text and nothing says so, because the skill is *listed*: the model
  never loads it unprompted, so the divergence surfaces only when someone types
  `/searxng`. `make skill.check` reports drift and exits non-zero. Both delegate
  to `bin/deploy-skills.sh`, which with no flag only previews; `--apply` writes.
  See `DESIGN.md`.
- **The skill is validated by agnix**, the linter the IDE plugin runs: `make
  skill.validate` fails on any `SKILL.md` that will not parse (an unquoted colon in
  the frontmatter, say) and proves its own pass by planting a broken one. `.agnix.toml`
  names the `claude-code` runtime rather than disabling the rule, because the skill's
  nested `metadata.hermes` is valid there and not under the generic spec.
  `.github/workflows/skills.yml` runs it and fails if it skipped. See `DESIGN.md`.
- **The skill ships code, not only prose**: `skills/searxng/scripts/sxq`. Editing it
  means `make skill.test` too — stdlib `unittest` over `skills/*/tests`, no venv
  needed. It is deliberately *not* part of `make test`, for the same reason
  `skill.check` is not: its verdict depends on state outside this repo.
- Commits: present tense, imperative, ≤72-char subject. Open an issue before
  large architectural changes.
