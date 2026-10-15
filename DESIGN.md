# DESIGN.md

Reference detail for this SearXNG checkout: repo layout, build system, test
infrastructure, toolchain quirks, and the fork-local deployment layer.
Read this when a task touches tooling, CI, themes, or the container.

The sibling files: `README.md` has the short "This fork" summary,
`AGENTS.md` has the short list of always-on rules.

---

## Repo layout

| Path | Owner |
|---|---|
| `searx/` | the application package. `searx/engines/` (253 modules), `searx/plugins/`, `searx/answerers/`, `searx/search/processors/`, `searx/result_types/`, `searx/enginelib/`, `searx/botdetection/`, `searx/network/`, `searx/favicons/` |
| `searx/settings.yml` | 3500-line **default** settings (see Runtime / config) |
| `searx/static/themes/simple/` | **committed build output** of `client/simple/` |
| `client/simple/` | frontend source: Vite + TypeScript + LESS, Biome + Stylelint |
| `searxng_extra/` | dev tooling: `update/` (data generators), `docs_prebuild/` |
| `tests/unit/`, `tests/robot/` | nose2 unit tests; Robot-Framework-style webapp tests |
| `utils/` | `lib*.sh` (sourced by `./manage`), `templates/etc/searxng/` |
| `container/`, `postman/` | fork-local, see Local deployment |
| `skills/searxng/` | fork-local: the `searxng` agent skill, see The searxng skill |
| `docs/` | Sphinx; `docs/dev/` is the developer documentation |
| `manage` + `Makefile` | build system, see below |

---

## The searxng skill

`skills/searxng/` is the **source of truth** for the agent skill that documents this
instance — its port, its categories, and the three engines that exist only in
`searx/engines/`. It is mirrored into the user skill hub at
`~/.agents/skills/searxng`, which is where Claude Code, OpenCode and Hermes load it
from.

That inverts the hub's own rule — *"~/.agents is the sole source of truth for
user-scoped shared capability"* — and it was adopted deliberately. The skill
describes a deployment this repo owns; a skill that documents a deployment belongs
next to the deployment, versioned with it, and reviewed in the same diff.

The cost is two copies and a sync step, so the sync is a target rather than a habit:

| Target | What it does |
|---|---|
| `make skill.sync` | `rsync -a --delete --delete-excluded` from `skills/searxng/` to `$SKILL_HUB/searxng/`, excluding `__pycache__` |
| `make skill.check` | `diff -r` the two trees; non-zero on drift, **skips cleanly** when no hub is present |
| `make skill.validate` | agnix over the repo: every `SKILL.md` parses; non-zero on an ERROR, **skips cleanly** when `uvx`/`jq` is absent |

Both targets delegate to `skills/sync.sh`, which is byte-identical to the copy in
`/opt/playground/firecrawl` and can be run directly. `$SKILL_HUB` defaults to `~/.agents/skills` and is overridable, which is how the
targets get tested against a scratch directory.

**Run `make skill.sync` after editing the skill.** Nothing else will tell you it is
needed. The skill is *listed* — gated in all three harnesses — so the model never
loads it unprompted, and a hub copy that has drifted keeps serving old text until
someone types `/searxng` and notices. That is the whole failure mode `skill.check`
exists to catch.

Two details that are load-bearing rather than tidy:

- **`--delete-excluded`, not just `--exclude`.** An excluded path is skipped by the
  transfer *and* left alone by `--delete`, so `__pycache__` would accumulate in the
  hub permanently. It is written there because the hub copy is read by path.
- **`skill.check` must not fail when the hub is absent.** CI and any other checkout
  have no `~/.agents`, and a build that fails for that reason teaches people to
  ignore the check.

| `make test.skill` | the same check, named in the `test.` namespace |

The skill is deliberately **not** part of `make test`. It is the one step whose
verdict depends on state outside this repository, so folding it in would let a
build go red for a reason unrelated to the code — and would start failing on any
commit if someone ever edits the hub copy directly, which is how a check teaches
people to ignore it. `test.skill` exists so it can be invoked from CI or a
pre-commit hook on its own.

`skill.validate` is the second half of the same problem. A `SKILL.md` whose
frontmatter will not parse (`AS-016`, the rule the IDE plugin reports as a broken
skill) is a skill none of the three harnesses can read — and because the hub copy is
the one they load, a break here is a break in the loaded skill. It runs agnix, the
linter behind that plugin, through `uvx`, so nothing is installed on PATH, and reads
`.agnix.toml`. That file names the **`claude-code` runtime** rather than disabling
`AS-016`: the skill carries nested `metadata.hermes`, which the universal Agent
Skills spec rejects and the runtime that actually loads this skill accepts — so the
rule is answered, not muted. Like `skill.check` it skips when the linter cannot be
fetched, and `.github/workflows/skills.yml` turns a skip back into a failure, because
a skipped validator validated nothing. The target also proves its own pass: it plants
a deliberately broken `SKILL.md` and fails if agnix does **not** report it, so a green
run is one that could have been red.

---

## Build system: `./manage` is the source of truth

`./manage` is a bash script that sources `utils/lib*.sh` and defines every task
as a shell function. The `Makefile` is a thin wrapper that maps
`make <name>` → `./manage <name>` for the names in its `MANAGE +=` block, plus
the grouped targets (`test`, `clean`, `all`). `make help` and `./manage help`
list them; `./manage --help` is the canonical source.

Rules that matter:

- **Do not run `pip install`, `black`, `pylint`, `nose2`, `sphinx-build` from a
  plain shell.** The toolchain lives in the venv at `local/py3`, and `./manage`
  puts `local/py3/bin` on PATH. To run anything inside it:
  `./manage pyenv.cmd <cmd> ...` (auto-creates the venv on first use).
- `make install` = editable `pip install -e ".[test]"` into `local/py3`.
- The venv is validated by a `requirements.sha256` stamp (`utils/lib.sh`,
  `pyenv.OK`). **Editing any `requirements*.txt` silently triggers a full venv
  rebuild** on the next `make` invocation.
- `make V=1 <target>` sets `VERBOSE=1`, which unsets the `@` and `set -x`, and
  adds `-vvv` to nose2 / `-v` to sphinx and pylint.
- `./manage dev.env` (or `dev.env <cmd>`) opens a `bash --norc --noprofile`
  subshell with the venv, Go tools and node on PATH. This is the environment the
  docs use for ad-hoc commands:
  `python -m searx.favicons`, `python -m searx.data`, `python -m searx.enginelib`,
  `searxng_extra/update/*.py`, and `SEARXNG_DEBUG=1 searxng-run` for pdb.
- `shfmt` is a **Go tool** (`go tool shfmt`, declared in `go.mod`), not a pip
  package. `format.shell` / `test.shfmt` only cover `./manage ./container ./utils`
  (`SHFMT_SCRIPTS` in `manage`).
- Toolchain versions are pinned in `mise.toml`: python 3.11, node 25,
  go 1.24.5, shellcheck 0.11.0, sqlite 3.40.1. `node.env` enforces
  `NODE_MINIMUM_VERSION=24.3.0` and installs via NVM.

---

## Tests

The runner is **nose2**, not pytest. There is no `nose2.cfg`; all configuration
lives in `utils/lib_sxng_test.sh`.

| Target | What it runs |
|---|---|
| `make test.unit` | `python -m nose2 -s tests/unit` |
| `make test.coverage` | unit tests with `--with-coverage --coverage searx`, then `coverage report` + `coverage html` |
| `make test.pybabel` | `pybabel extract` (only in `ci.test`) |
| `make test.pylint` | two pylint passes, see below |
| `make test.black` / `test.yamllint` / `test.shfmt` / `test.rst` | formatters and linters in check mode |
| `make test.robot` | `python -m tests.robot`, needs geckodriver + a real browser |
| `make test` | yamllint black pyright_modified pylint unit robot rst shell shfmt |
| `make ci.test` | `make test` + `test.pybabel` — this is what CI runs |

### Running a single test

**Use the fully dotted module path:**

```sh
./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_query
./manage pyenv.cmd python -m nose2 -s tests/unit tests.unit.engines.test_xpath
./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_search.SearchTestCase
```

The bare-name form appears to work but is wrong:

```sh
nose2 -s tests/unit test_query     # silently skips tests/unit/__init__.py
```

`tests/unit/__init__.py` is what sets
`os.environ['SEARXNG_SETTINGS_PATH'] = tests/unit/settings/test_settings.yml`
and sets `SEARXNG_DEBUG=0`. Importing the module as `tests.unit.*` runs it;
importing it as top-level `test_query` does not, so the suite silently runs
against production default settings. Always pass `tests.unit....`.

### Traps

- **`test.pyright` always exits 0.** `utils/lib_sxng_test.sh` calls basedpyright
  and then `return 0`, deliberately discarding the result. `make test` runs
  `test.pyright_modified`, which checks only `.py` files reported by
  `git status --porcelain` — so it checks *nothing* on a clean tree.
  `pyrightconfig.json` points at the venv (`venvPath: local`, `venv: py3`) and
  sets per-root strictness; `searxng_extra` and `tests` are mostly relaxed.
- **Fork change (2026-10-11): `test.pyright_modified` now gates.** It runs at
  `--level error` and honours the exit code, so touching a `.py` file with a
  type error fails `make test`. Verified in both directions — clean files exit
  0, a file with `reportOptionalMemberAccess` exits 1.

  Two things could not be done, and both were measured rather than assumed:

  - **The full tree cannot be gated.** `basedpyright --level error` over the
    repo reports **535 pre-existing errors**, so switching `test.pyright` on
    would turn `make test` red for everyone. That check stays advisory.
  - **Warnings cannot be a gate.** The untyped engine API produces ~120
    `reportUnknown*` / `reportMissingParameterType` findings on the four fork
    engines alone, none of them defects. Gating on warnings would be noise.

  Errors are what catch defects, and this did: `reportOptionalMemberAccess`
  on `dnarynkow.py`'s `_ticker` — the same regex run twice, guard deciding on
  one call and body dereferencing the other — was a real smell no unit test
  could see. It is fixed.

  **`nodejs_wheel` (206 MB, a third of the venv) is load-bearing.** basedpyright
  imports it and dies without it; the host's nvm node does not satisfy it.
  Keeping the check working costs that, and the two gaps compound — with the
  package gone, basedpyright prints `ModuleNotFoundError` and, before this
  change, nothing failed.
- **`test.pylint` runs pylint twice with different rules**:
  1. `searx/engines` with `--additional-builtins="traits,logger,categories"`.
     Engine modules are namespace-injected, so those names have no import and
     would otherwise be undefined.
  2. `searx searxng_extra tests` with `--ignore-paths=searx/engines`.

  Adding a new top-level Python package means editing `utils/lib_sxng_test.sh`
  — it is not picked up automatically. `.pylintrc` sets
  `extension-pkg-whitelist=lxml.etree`, `jobs=0`, `max-line-length=120`.
- **`black` config lives in `manage` (`BLACK_OPTIONS`), not `pyproject.toml`:**
  `--target-version py311 --line-length 120 --skip-string-normalization`.
  `BLACK_TARGETS` covers `searx`, `searxng_extra`, `tests`, excluding
  `searx/static` and `searx/languages.py`, and `--include 'searxng.msg|\.pyi?$'`
  so `searx/searxng.msg` (the translation catalogue) is black-formatted too.
- `test.rst` runs `rst2html --halt error` over `README.rst` only
  (`RST_FILES` in `manage`).
- `make test.robot` needs geckodriver (`GECKODRIVER_VERSION=v0.37.1`,
  auto-downloaded by the `gecko.driver` task) and a real Firefox. It is part of
  `make test`, so expect it to be the slow step.
- `YAMLLINT_FILES` is generated from `git ls-files`, so **untracked YAML is never
  linted**. `tests/unit/settings/syntaxerror_settings.yml` is explicitly excluded
  because it is a fixture that must not parse.
- `.coveragerc`: branch coverage, `source = searx`.

---

## Runtime / config

- Entry point `searx/webapp.py` (`app = Flask(__name__, static_folder=None)`),
  served by **granian** in WSGI mode — not the Flask dev server. The console
  script `searxng-run` (`setup.py` entry point) wraps `searx.webapp.run`.
  `make run` = the `webapp.run` task: sets `SEARXNG_DEBUG=1`,
  `GRANIAN_RELOAD=true`, `GRANIAN_RELOAD_PATHS=./searx`, and listens on `::8888`.
- `searx/settings.yml` is the **default** settings shipped with the source.
  Real instances set `use_default_settings: true` and override a subset; the
  merge happens in `searx/settings_loader.py`, which also understands
  `use_default_settings.engines.remove` and `.keep_only`.
- `SEARXNG_SETTINGS_PATH` may point at a **file or a folder**. Resolution order
  is in `settings_loader.load_settings` (env var wins, then the user config
  folder).
- Many keys carry inline `# Is overwritten by ${SEARXNG_...}` comments —
  `SEARXNG_SECRET`, `SEARXNG_BIND_ADDRESS`, `SEARXNG_PORT`, `SEARXNG_BASE_URL`,
  `SEARXNG_LIMITER`, `SEARXNG_METHOD`, `SEARXNG_IMAGE_PROXY`,
  `SEARXNG_VALKEY_URL`, `SEARXNG_DEBUG`.
- **Engine wiring.** `searx/settings.yml` `engines:` is a list of dicts, each
  with `name:` (display name) and `engine:` (module basename under
  `searx/engines/`). `searx/engines/__init__.py` `load_engine()`:
  1. `load_module(engine + '.py', ENGINE_DIR)` — a `sys.exit(1)` on
     SyntaxError/ImportError, so a broken engine module kills startup.
  2. `update_engine_attributes()` injects `ENGINE_DEFAULT_ARGS`
     (`engine_type`, `paging`, `categories`, `shortcut`, `timeout`,
     `language_support`, `about`, `weight`, …) for any attribute not already set,
     then applies the YAML entry on top.
  3. Traits from `searx/data/engine_traits.json` are attached.
  4. `is_engine_active()` — `inactive: true` skips the engine entirely (89
     entries use it); `'onions'` category engines are skipped unless Tor is on.
  5. `is_missing_required_attributes()` — **any attribute not starting with `_`
     that is `None` drops the engine silently.** This is the classic "my engine
     doesn't show up" cause.
  6. `setup()` is called if defined.

  Constraints: engine `name` must be lowercase (auto-converted with a warning)
  and must **not contain an underscore**. `set_loggers()` injects a per-engine
  `logger` into every `searx.engines.*` module.
- Two engine styles coexist: plain module namespaces (e.g.
  `searx/engines/wikipedia.py`) and the `searx.enginelib.Engine` class API.
  New engines should use the class API. `searx/enginelib/__main__.py` provides
  a CLI (`python -m searx.enginelib cache state`, `init`, …).
  Docs: `docs/dev/engines/` (`enginelib`, `engine_overview`, and per-engine
  pages under `online/`, `offline/`, `online_url_search/`).
- `engine_type` selects the search processor that runs the engine:
  `searx/search/processors/{online,offline,online_url_search,online_currency,online_dictionary}.py`.

---

## Generated and committed artifacts

- **Frontend build output is committed.** `client/simple/` builds into
  `searx/static/themes/simple`, and `STATIC_BUILT_PATHS` in
  `utils/lib_sxng_static.sh` is exactly:
  `searx/templates/simple/icons.html`, `searx/static/themes/simple`,
  `client/simple/package-lock.json`.
  A theme change therefore needs **two** commits, in this order:
  1. `make static.build.restore` — `git restore` the build products, commit only
     your source.
  2. `make static.build.commit` — requires a **clean working tree** (it aborts
     on unstaged or staged changes), drops the previous build commit
     (`static.build.drop`), then runs `themes.fix`, `themes.lint`, `themes.all`,
     stages exactly `STATIC_BUILT_PATHS`, and commits as `[build] /static`.
     It dies if the build produced files outside `STATIC_BUILT_PATHS`.
  `make static.build.drop` rewinds that commit if it was never pushed.
- Theme tasks (`utils/lib_sxng_themes.sh`, `utils/lib_sxng_vite.sh`):
  `themes.all` / `themes.simple` (vite build), `themes.lint`
  (biome + `tsc --noEmit`), `themes.fix` (stylelint + biome +
  `sort-package-json`), `themes.simple.analyze` (`VITE_BUNDLE_ANALYZE=true`).
  Every build first regenerates `searx/templates/simple/icons.html` via
  `searxng_extra/update/update_pygments.py` (`templates.simple.pygments`).
  `vite.simple.dev` is commented out in `lib_sxng_vite.sh` — there is no
  frontend dev server; use `LIVE_THEME=simple make run` for live rebuilds.
  CI's Theme job (`.github/workflows/integration.yml`) runs
  `make themes.lint` then `make themes.all` on Node 26.
- **Generated data files.** `searx/sxng_locales.py`, `searx/data/*.json`
  (`engine_traits`, `locales`, `currencies`, `useragents`, `external_bangs`,
  `engine_descriptions`, `osm_keys_tags`, `wikidata_*`), `searx/data/ahmia_blacklist.txt`.
  Regenerate with `make data.all` (or `data.traits` / `data.locales` /
  `data.useragents` / `data.currencies`), which shells out to
  `searxng_extra/update/*.py`. Each file's docstring says it is generated —
  do not hand-edit.
- **Docs.** `make docs.html` runs `docs.prebuild` first, which calls
  `utils/searxng.sh searxng.doc rst` and `searxng_extra/docs_prebuild` to
  generate `build/docs/includes/*.rst` (gitignored) that the Sphinx toctrees
  `include` — editing a `.rst` include that does not exist yet is a dead end.
  `make docs.live` (sphinx-autobuild) watches `./searx` and `*.rst|py|yml`.
- `searx/version.py` derives the version from git at runtime; it only falls back
  to importing `searx.version_frozen` if that module exists. That file is
  **not** produced by `make` — it is written by `python -m searx.version freeze`
  for archive builds outside a git repository, and it is gitignored.

---

## Local deployment (fork-local, not upstream)

`container/` and `postman/` exist only in this fork. The trick that keeps them
mergeable: `container/docker-compose.override.yml` is loaded automatically by
docker compose alongside upstream's `container/docker-compose.yml`, so upstream
changes to the base file do not conflict.

- `container/.env` — **committed**: pinned `SEARXNG_VERSION` (tag + digest),
  `SEARXNG_HOST` / `SEARXNG_PORT` / `SEARXNG_BASE_URL`, `FORCE_OWNERSHIP`.
- `container/.env.prod` — **gitignored** (see the `.gitignore` entry), holds
  `SEARXNG_SECRET` and `GITHUB_PERSONAL_ACCESS_TOKEN`. Never commit it.
  Compose passes it into the container through `env_file`, so it is the only
  place a credential may live here: `settings.yml` is **tracked**, and nothing
  in the settings schema accepts a `$ENV` override for an engine key
  (`grep -c "env=" searx/settings_defaults.py` is 0), so a token written into
  settings.yml would reach the repository's history.
- **A credential in `.env.prod` does nothing until its consumer exists.**
  `MASSIVE_API_KEY` and `FINANCIAL_DATASETS_API_KEY` also sit there, but no
  SearXNG engine reads either — they are portfolio credentials, sourced from
  `/etc/hermes/.env`. Harmless because the file is gitignored; noted so their
  presence is not mistaken for wiring.
- `container/core-config/settings.yml` — bind-mounted over `/etc/searxng`.
  Owned by the host user because `FORCE_OWNERSHIP=false`, so it can be edited
  in place and applied with `docker restart searxng-core`.
- **The container runs the pinned upstream image, not this repo's source.**
  Anything edited under `searx/` here is inert until it is bind-mounted in
  `docker-compose.override.yml`, and that failure is silent: the repo looks
  patched while the container keeps the image's copy. Currently mounted —
  `liferay_forum.py`, `sii.py`, `dnarynkow.py`, `ksiazak.py` (fork-local) and
  `github.py` (an upstream engine patched fork-side to read the GitHub token
  from the environment). Check with
  `docker exec searxng-core grep -c GITHUB_PERSONAL_ACCESS_TOKEN /usr/local/searxng/searx/engines/github.py`,
  not by reading the repo.
- It sets `use_default_settings: true` and crucially
  `search.formats: [html, json]`. SearXNG ships with `html` only, and the
  Firecrawl instance at `/opt/playground/firecrawl` consumes
  `GET {SEARXNG_ENDPOINT}/search?q=...&format=json` as its search provider.
  Dropping `json` does not error: it returns **HTTP 200 with no `.results`
  array**, which reads as "engine returned nothing" rather than "misconfigured".
- The engine enable/disable list in that file carries the probe date and the
  reason per engine (CAPTCHA, HTTP 429 with 180 s suspensions, "access denied").
  Re-probe before re-enabling any of them; the current egress IP is what was
  probed.
- **`bing news` is the only enabled news engine that supports `time_range`.**
  SearXNG *drops* every engine whose `time_range_support` is False when a range
  is set, and all four others in `news` are False, so `-c news` plus a
  `time_range` used to run **zero** engines and answer with an empty result and
  an empty `.unresponsive_engines` — a healthy-looking empty. The block is
  additionally pinned to `enable_http3: false`, because `bing_news.py` asks for
  HTTP/3 and UDP/443 is filtered on this egress: QUIC fails with
  `curl (56) ngtcp2_conn_writev_stream ERR_DRAINING` before a request leaves,
  which is what the file's older "connection error" note recorded. No upstream
  engine file is patched for this — SearXNG copies every settings key onto the
  engine module (`searx/engines/__init__.py`, the `setattr` loop over
  `engine_data`), so one line does it. Verified 2026-10-15: 4 results for
  `-c news --time-range week`, all `bing news`.
- **`sii` filters on every query term.** sii.org.pl ORs the terms of
  `/szukaj?search=` and matches fragments, so `zzqxv term` returned the same ten
  rows as `term`. `sii` is in `general`, which put those ten unrelated rows into
  every default search — 10 of 96 for `q=ECB interest rate`, and therefore into
  Firecrawl's results. `searx/engines/sii.py` keeps a row only when **every**
  term appears in its title or teaser, folded case- and diacritic-insensitively
  (`ł`→`l` explicitly, which NFKD alone does not do). The OR happens
  server-side, so a filter in `response()` is the only place that can see both
  the query and the row. The filter's cost is otherwise invisible — a query
  whose rows all use a synonym (`PKN` for `Orlen`) returns empty, and empty
  looks the same from outside — so it logs `dropped N of M row(s)` at **debug**
  with the query. Debug, not warning: a synonym miss is an accepted outcome of
  the design, and a warning here would train people to ignore the ones that
  matter. This instance runs `general.debug: false`, so the line appears only
  for an operator who has turned debug on.
- **Pinning an engine this instance does not have runs the default search, and
  says nothing.** `engines=mojeek news` returns 96 results from `mwmbl`,
  `duckduckgo web` and `sii`. That is upstream behaviour and is not worked
  around here; `sxq` detects it instead — each result carries its `engines`, so
  the skill's own tool compares them against the pin and warns on stderr, and
  warns again when a `time_range` came back empty with nothing failing.
- SearXNG has **no authentication.** The compose port is published on a LAN
  address deliberately, making it an open search proxy for the LAN. Do not
  publish it beyond a trusted network.
- The published port is **8888, not 8080** (moved 2026-10-11). 8080 is what a
  dozen common images default to — Jupyter, dev servers, proxies — so it is the
  port most likely to collide with something else on this host. The instance
  binds the LAN address, **not loopback**: `localhost:8888` is refused even
  though 8888 is the published port, which trips up any borrowed script that
  defaults to `http://localhost`.
- `SEARXNG_BASE_URL` must name the address the instance is actually published
  on. The docs state it is "used to create correct inbound links", and with
  `http://localhost:8888/` every generated link — the RSS alternate on each
  search page, two in `/preferences` — pointed at an address that refuses
  connections, including from this host. The `server.port` comment in
  settings.yml says that key is "ignored in the container", which is true and
  very easy to read as "nothing in this block matters".
- **Changing the port means restarting every consumer, and a consumer left
  behind does not fail loudly.** Firecrawl ran for 8 hours after the move with
  `SEARXNG_ENDPOINT` still on `:8080` inside its process: search still returned
  results, because it fell back to another provider. Configuring SearXNG as the
  search provider was silently undone. Check the *process*, not the file —
  `docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' firecrawl-api-1 | grep SEARXNG`.
  The port appears in five places: `container/.env` (`SEARXNG_PORT`,
  `SEARXNG_BASE_URL`), `core-config/settings.yml` (`server.port`),
  `firecrawl/.env`, `/etc/hermes/.env`, and the Postman environment — which
  exists twice, in the repo and in the Postman cloud, and the collection
  carries its own `searxngUrl` variable that the environment shadows locally.
- The `valkey` service is defined but unused by default (limiter off, no
  `valkey.url`); it sits behind the `valkey` compose profile —
  `docker compose --profile valkey up -d`.
- `postman/run.sh` is the integration smoke test (newman) against that running
  instance: `./postman/run.sh`, `./postman/run.sh --folder "Direct JSON search"`,
  `SEARXNG_URL=http://127.0.0.1:8888 ./postman/run.sh`. The collection checks
  `/config`, direct JSON search, news, images, and strict safesearch. Run it
  after changing `container/core-config/settings.yml` or the pinned image.
- **`test.robot` needs a real `firefox` binary on PATH, not a packaging
  wrapper.** Two host facts make it fail in ways that name neither cause nor fix:
  - Ubuntu's `/usr/bin/firefox` is a **snap shim** — a shell script. Selenium's
    Selenium Manager probes it, reads `Mozilla Firefox 157.0.1` off it, and hands
    *geckodriver* the shim; geckodriver execs it, it exits 1, and the whole suite
    dies with `Process unexpectedly closed with status 1`. `tests/robot/__main__.py`
    resolves both binaries from PATH and passes them in, so the browser under
    test is the one on PATH rather than a second one found by another search.
  - The snap's `geckodriver` cannot be signalled from outside its confinement, so
    a failed run **leaks one process per test** that neither `pkill` nor
    selenium's own `terminate()` can reap — `service.terminate()` raises
    `PermissionError`. The cause is **AppArmor**, not snapd or permissions: the
    process runs under `snap.firefox.geckodriver (enforce)` while an ordinary
    shell is `unconfined`, in the *same* user namespace and the *same* uid, and
    the profile has no rule letting an unconfined process signal it. A failed
    run on 2026-10-15 left 48 of them holding 273 MB.
  - `snap stop firefox` does **not** reap them — that snap exposes no services,
    so `snap start/stop/restart firefox` all answer `has no services`. Signal
    them from inside the confinement instead, which is the only context AppArmor
    permits: `snap run --shell firefox -c 'kill -9 $(pgrep -x geckodriver)'`.
    Check with `pgrep -xc geckodriver`.
  So this host carries a plain Firefox under `local/firefox` with
  `local/py3/bin/firefox` pointing at it (`manage` puts `local/py3/bin` first on
  PATH). `local/` is gitignored, so this is environment, not repository.
- **`gecko.driver` checks the driver it installed, not the one on PATH.**
  `manage gecko.driver` unpacks a pinned geckodriver into `${PY_ENV_BIN}`, but
  the "already installed" test used to run bare `geckodriver -V` — which the snap
  satisfies. It therefore reported success while `${PY_ENV_BIN}/geckodriver` did
  not exist, and `test.robot` went on to run on a driver nobody chose. Verified
  2026-10-15 by moving the file away: the old check said "already installed", the
  new one downloads the pin.
- **`shellcheck` is not installed by `manage`** and `test.shell` calls it by bare
  name from the Makefile, so it must be on the ambient PATH (`~/.local/bin` here)
  or that step cannot run. It is the one `make test` dependency with no target to
  install it.

---

## Tooling and CI

- `.github/workflows/integration.yml` is the main gate: a Python matrix
  (3.11–3.14) running `make V=1 install` then `make V=1 ci.test`, plus the
  Theme job (lint + build). Other workflows: `container.yml`, `data-update.yml`,
  `documentation.yml`, `l10n.yml`, `sync.yml`, `ai-policy.yml`.
- `ai-policy.yml` runs `.github/scripts/aiPolicy.mjs` on newly opened issues and
  PRs from first-time contributors and closes them unless they accept
  `AI_POLICY.rst`. That policy requires disclosure of AI assistance and
  human-written issue/PR descriptions.
- Translations live in `searx/translations/`, extracted from `*.py`, `*.html`
  (Jinja) and `searx/searxng.msg` via the custom `searxng_msg` extractor
  (`searx/babel_extract.py`, configured in `babel.cfg`). Upstream syncs with
  Weblate through `utils/lib_sxng_weblate.sh`, which operates on a separate
  `translations` branch in a git worktree under `cache/`.
- `.editorconfig`: Python 4 spaces (editor `max_line_length = 80` even though
  black allows 120), shell 4 spaces with `switch_case_indent`, `*.html`/`*.css`/
  `*.less`/`*.js`/`*.ts`/`*.json`/`*.yml` 2 spaces, Makefiles tabs,
  `docs/**.rst` max line length 79.
- `.yamllint.yml`: `extends: default`, indentation 2, line-length 120 as a
  warning only, `document-start`/`document-end` disabled.
- `.devcontainer/` provides a Debian bookworm devcontainer with the venv paths
  wired into the VS Code Python extension; `.vscode/tasks.json` defines
  `make run` (default build task) and `make docs.live`.