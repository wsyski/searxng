# Finance Search Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is superpowers:test-driven-development: the failing test is written and **seen failing** before the fix.

**Goal:** Stop the instance from returning finance results that look healthy and are not: `sii` rows that match one word of a multi-word query, news searches with a time range that silently return zero, and pinned-engine searches that silently run the default engines.

**Architecture:** Two fork engine fixes (`searx/engines/sii.py`, `searx/engines/dna_rynkow.py`), one settings change (`container/core-config/settings.yml`), two diagnostics in the skill's `sxq`, and Postman negative controls. No upstream file changes. The container runs the pinned upstream image with the fork engines bind-mounted, so every engine change is verified **inside the container** after a restart.

**Tech Stack:** Python 3.11+ (SearXNG engine API), nose2 via `./manage`, newman (`postman/run.sh`), docker compose.

**Spec:** [docs/superpowers/specs/2026-10-15-finance-search-quality-design.md](../specs/2026-10-15-finance-search-quality-design.md). It holds the measurements and decisions D1–D7; this plan holds only the mechanics.

## Global Constraints

- **`./manage` is the toolchain.** Never bare `pip`/`black`/`pylint`/`nose2`. Single test, dotted path only: `./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_engine_sii` — the bare form silently loads production settings (`DESIGN.md` → Tests).
- **`make test` must stay green**, including `test.pyright_modified` (gates at error level on modified files) and `test.pylint` (engines pass uses `--additional-builtins`).
- **Black:** line length 120, `--skip-string-normalization`.
- **The instance is live and Firecrawl searches through it.** Restart only with `docker restart searxng-core`; never change the published address, port or exposure.
- **`sii` rate-limits hard** (two or three searches, then 429 and a one-hour suspension). Live probes against `sii` are spaced ≥ 8 s and kept to the ones listed here.
- **Skill edits are followed by `make skill.sync`, `make skill.check`, `make skill.validate`.**
- **Commits:** present tense, imperative, ≤ 72-char subject, one per task. AI assistance is disclosed per `AI_POLICY.rst`; any upstream issue or PR text is written by the human.

## Review Focus

- Task 2's filter must not pass vacuously: the negative fixture is the **same block** that the positive fixture accepts, differing only in the query.
- Task 4 changes what Firecrawl sees on news searches. Check Firecrawl's process env (`docker inspect … | grep SEARXNG`), not its `.env`, if anything looks off afterwards.

---

### Task 0: Re-verify the measurements from the host

The spec's numbers were taken from a LAN VM whose direct requests to sii.org.pl get 403. Re-take the two that decide the design, from the host.

- [x] **Step 1: Confirm the site ORs terms (direct, host)**

```bash
for q in 'zzqxv' 'zzqxv+term' 'term'; do
  printf '%-12s ' "$q"
  curl -s -A 'SearXNG/1.0' "https://www.sii.org.pl/szukaj?search=$q" | grep -c 'class="newsabout"'
  sleep 8
done
```

Expected: `zzqxv 0` (or a 404 body), `zzqxv+term` ≈ `term` ≈ 10. If `zzqxv+term` is 0, the site ANDs terms and the defect is in how SearXNG passes the query: stop, record the finding in the spec, and do Task 1 before re-measuring.

- [x] **Step 2: Confirm the news time-range gap and the bing news probe**

```bash
SX=http://192.168.1.100:8888
curl -sG $SX/search --data-urlencode q='ECB interest rate' --data-urlencode categories=news \
  --data-urlencode time_range=week --data-urlencode format=json | jq '.results|length, .unresponsive_engines'
curl -sG $SX/search --data-urlencode q='ECB interest rate' --data-urlencode engines='bing news' \
  --data-urlencode time_range=month --data-urlencode format=json | jq '[.results[].engine]|group_by(.)|map({(.[0]):length})|add'
```

Expected: `0` / `[]`, then `{"bing news": N}` with N > 0. If bing news fails, Task 4 becomes "record and skip".

No commit.

> **What actually happened.** Step 1 confirmed the site ORs: `zzqxv` → 0, `zzqxv+term` → 10,
> `term` → 10. Step 2's first command printed the expected `0` / `[]`; the second printed
> `null`, meaning `bing news` returned nothing at all. So the "record and skip" contingency
> fired — and skipping would have left defect 2 in place, because enabling `bing news` as
> written still returns zero.
>
> The cause is the transport. `bing_news.py` sets `enable_http3 = True`, so SearXNG asks
> curl_cffi for HTTP/3, and UDP/443 is filtered on this egress. The "connection error" the
> settings file recorded on 2026-10-10 was never bing being down. Task 4 therefore adds
> `enable_http3: false` beside `disabled: false` — still a settings-only change, since
> `searx/engines/__init__.py` `setattr`s every settings key onto the engine module. Details
> and measurements are in the spec; the decision row is D5.

---

### Task 1: URL-encode the query in `sii` and `dna_rynkow`

**Files:**
- Modify: `searx/engines/sii.py` (`request`)
- Modify: `searx/engines/dna_rynkow.py` (`request`)
- Test: `tests/unit/test_engine_sii.py`, `tests/unit/test_engine_dna_rynkow.py`

- [x] **Step 1: Write the failing tests**

In `SiiEngineTests`:

```python
    def test_request_encodes_reserved_characters(self):
        """A raw f-string turned `AT&T` into search=AT plus a stray `T` parameter."""
        params = {"headers": {}}
        self.engine.request("AT&T C#", params)
        self.assertIn("search=AT%26T+C%23", params["url"])
```

In the DNA test class:

```python
    def test_request_encodes_reserved_characters(self):
        params = {"pageno": 2}
        self.engine.request("AT&T", params)
        self.assertIn("search=AT%26T", params["url"])
        self.assertTrue(params["url"].endswith("&page=2"))
```

- [x] **Step 2: Run, see both fail**

```bash
./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_engine_sii tests.unit.test_engine_dna_rynkow
```

Expected: the two new tests FAIL with `search=AT&T` in the URL.

- [x] **Step 3: Implement**

`sii.py` — add `from urllib.parse import urlencode` and:

```python
def request(query, params):
    # `search`, never `q` — see the module docstring.
    params["url"] = f"{base_url}/szukaj?" + urlencode({"search": query})
```

(keep the rest of the function as is). `dna_rynkow.py`:

```python
    params["url"] = f"{base_url}/spolki/?" + urlencode({"search": query, "page": page})
```

- [x] **Step 4: Run, see all pass** (same command). The existing `test_request_uses_search_not_q` must still pass.

- [x] **Step 5: Commit**

```bash
git add searx/engines/sii.py searx/engines/dna_rynkow.py tests/unit/test_engine_sii.py tests/unit/test_engine_dna_rynkow.py
git commit -m "Encode the query in the sii and dna rynkow request URLs"
```

---

### Task 2: Keep a `sii` row only when every query term is in it (D1, D2)

**Files:**
- Modify: `searx/engines/sii.py` (`response`, new `_fold`, `_terms`)
- Test: `tests/unit/test_engine_sii.py`

- [x] **Step 1: Give the test response a query**

`resp.search_params["query"]` is what the engine will read (the online processor sets it; `open_meteo.py`, `dictzone.py` read it the same way). Change the helper so every existing test carries a query its fixtures match:

```python
def _resp(text, status_code=200, query="orlen"):
    r = Mock()
    r.text = text
    r.status_code = status_code
    r.search_params = {"query": query}
    return r
```

Run the module once: everything still passes (no behaviour change yet).

- [x] **Step 2: Write the failing tests**

```python
    # -- relevance: the site ORs terms -------------------------------------

    TERM_BLOCK = COMMENT_BLOCK.replace("Spółka tygodnia: ORLEN", "Termin walnego zgromadzenia")

    def test_one_matching_word_of_two_is_not_a_match(self):
        """Measured 2026-10-15: `zzqxv term` returned the same ten rows as `term`."""
        results = self.engine.response(_resp(self.TERM_BLOCK, query="zzqxv term"))
        self.assertEqual(len(results), 0)

    def test_the_same_block_matches_when_every_term_is_present(self):
        """The control for the test above - same block, different query."""
        results = self.engine.response(_resp(self.TERM_BLOCK, query="termin walnego"))
        self.assertEqual(len(results), 1)

    def test_terms_match_across_title_and_teaser(self):
        # "orlen" in the title, "korekta" only in the teaser
        results = self.engine.response(_resp(COMMENT_BLOCK, query="orlen korekta"))
        self.assertEqual(len(results), 1)

    def test_matching_ignores_case_and_polish_diacritics(self):
        for q in ("SPOLKA tygodnia", "spółka TYGODNIA", "Spolka Tygodnia"):
            self.assertEqual(len(self.engine.response(_resp(COMMENT_BLOCK, query=q))), 1, q)

    def test_l_with_stroke_folds_to_l(self):
        """NFKD leaves Ł alone; the portfolio repo paid for that once (ISIN_MAP test)."""
        block = COMMENT_BLOCK.replace("Spółka tygodnia: ORLEN", "Złoto i miedź")
        self.assertEqual(len(self.engine.response(_resp(block, query="zloto"))), 1)

    def test_a_single_absent_term_is_not_a_match(self):
        self.assertEqual(len(self.engine.response(_resp(COMMENT_BLOCK, query="kghm"))), 0)

    def test_an_empty_query_keeps_rows(self):
        """No terms, nothing to require - do not turn a parsing test into a filter test."""
        self.assertEqual(len(self.engine.response(_resp(COMMENT_BLOCK, query=""))), 1)
```

- [x] **Step 3: Run, see them fail**

```bash
./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_engine_sii
```

Expected FAIL: `test_one_matching_word_of_two_is_not_a_match` (1 != 0), `test_a_single_absent_term_is_not_a_match` (1 != 0). The positive controls pass already — that is correct and is why they exist.

- [x] **Step 4: Implement**

```python
import unicodedata

# NFKD decomposes ó/ś/ż into base + combining mark, but Ł/ł is a letter of its own.
_FOLD_EXTRA = str.maketrans({"ł": "l", "Ł": "l"})


def _fold(text):
    text = (text or "").translate(_FOLD_EXTRA)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _terms(query):
    return [t for t in _fold(query).split() if t]
```

In `response()`, before the loop: `terms = _terms(resp.search_params.get("query", ""))`. Inside the loop, after computing `title` and `content`:

```python
        haystack = _fold(title + " " + content)
        # sii.org.pl ORs the terms and matches fragments, so a row is ours only
        # if EVERY term is in what we can see of it. Measured 2026-10-15:
        # `zzqxv term` returned the same ten rows as `term`. See the docstring.
        if any(t not in haystack for t in terms):
            continue
```

Add an `.. attention::` paragraph to the module docstring with the measurement table from the spec.

- [x] **Step 5: Run the module, then the engine lint and type gates**

```bash
./manage pyenv.cmd python -m nose2 -v -s tests/unit tests.unit.test_engine_sii
make test.pylint test.black test.pyright_modified
```

Expected: all pass.

- [x] **Step 6: Mutation check** — replace `any(` with `all(` in the guard, rerun the module, confirm `test_one_matching_word_of_two_is_not_a_match` fails; restore.

- [x] **Step 7: Commit**

```bash
git add searx/engines/sii.py tests/unit/test_engine_sii.py
git commit -m "Drop sii rows that do not contain every query term"
```

---

### Task 3: Apply Tasks 1–2 to the running container and verify there

**Files:** none changed.

- [x] **Step 1: Restart and confirm the container serves the new code**

```bash
docker restart searxng-core
docker exec searxng-core grep -c '_fold' /usr/local/searxng/searx/engines/sii.py   # expect >= 2
docker exec searxng-core grep -c 'urlencode' /usr/local/searxng/searx/engines/dna_rynkow.py  # expect >= 1
```

- [x] **Step 2: Live controls (spaced for the rate limit)**

```bash
SX=http://192.168.1.100:8888
for q in 'zzqxv term' 'orlen' 'cd projekt'; do
  printf '%-12s ' "$q"
  curl -sG $SX/search --data-urlencode "q=$q" --data-urlencode engines=sii --data-urlencode format=json \
    | jq -c '[(.results|length), .unresponsive_engines]'
  sleep 10
done
```

Expected: `zzqxv term` → `[0,[]]`; `orlen` and `cd projekt` → `[N>0,[]]`, every title/content containing both words for `cd projekt`.

- [x] **Step 3: General search no longer carries unrelated sii rows**

```bash
curl -sG $SX/search --data-urlencode q='ECB interest rate' --data-urlencode format=json \
  | jq '[.results[] | select(.engine=="sii")] | length'
```

Expected: `0` (was 10 on 2026-10-15). No commit.

---

### Task 4: Enable `bing news` so news time ranges return results (D5)

**Files:**
- Modify: `container/core-config/settings.yml` (the news block)

- [x] **Step 1: Record the failing state** — Task 0 Step 2's first command prints `0` / `[]`.

- [x] **Step 2: Edit the news block**

```yaml
  # News: duckduckgo news, wikinews (default on), qwant news and bing news answer.
  # None of the first three supports time_range, and SearXNG drops an engine that
  # does not when a range is set - so `-c news` + `time_range` ran ZERO engines and
  # returned an empty, error-free response. bing news supports it. Re-probed
  # 2026-10-15 (disabled 2026-10-10 for "connection error"): 10 results with no
  # range, 8 with time_range=month. google news ("access denied"), reuters (HTTP
  # error, still on 2026-10-15) and brave.news (crash) stay off. mojeek news,
  # startpage news and yahoo news are `inactive` upstream (proof-of-work captchas).
  - name: qwant news
    disabled: false
  - name: bing news
    disabled: false
  - name: google news
    disabled: true
  - name: reuters
    disabled: true
  - name: brave.news
    disabled: true
```

- [x] **Step 3: Lint, restart, verify**

```bash
make test.yamllint
docker restart searxng-core
curl -sG http://192.168.1.100:8888/search --data-urlencode q='ECB interest rate' --data-urlencode categories=news \
  --data-urlencode time_range=week --data-urlencode format=json | jq '.results|length, ([.results[].engine]|unique)'
```

Expected: a positive count, engines `["bing news"]`.

- [x] **Step 4: Check Firecrawl still uses this instance** (it inherits the enabled set):

```bash
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' firecrawl-api-1 | grep SEARXNG
```

Expected: `SEARXNG_ENDPOINT=http://192.168.1.100:8888`, `SEARXNG_NEWS_CATEGORIES=news`.

- [x] **Step 5: Commit**

```bash
git add container/core-config/settings.yml
git commit -m "Enable bing news so a news time range runs an engine"
```

---

### Task 5: `sxq` names the two silent failures (D6)

**Files:**
- Modify: `skills/searxng/scripts/sxq`
- Create: `skills/searxng/tests/test_sxq.py` (stdlib `unittest`, imports `sxq` via `importlib.machinery.SourceFileLoader` because the file has no `.py` suffix)

- [x] **Step 1: Write the failing tests**

```python
import importlib.machinery, importlib.util, io, os, unittest
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("sxq", os.path.join(HERE, "..", "scripts", "sxq"))
_spec = importlib.util.spec_from_loader("sxq", _loader)
sxq = importlib.util.module_from_spec(_spec)
_loader.exec_module(sxq)  # load_module() is gone in current Pythons


class Diagnostics(unittest.TestCase):
    def _err(self, fn, *a):
        buf = io.StringIO()
        with redirect_stderr(buf):
            fn(*a)
        return buf.getvalue()

    def test_results_from_unpinned_engines_are_named(self):
        payload = {"results": [{"engines": ["mwmbl"]}, {"engines": ["sii"]}]}
        err = self._err(sxq.report_foreign_engines, payload, "mojeek news")
        self.assertIn("mojeek news", err)
        self.assertIn("mwmbl", err)

    def test_pinned_engines_that_answered_are_quiet(self):
        payload = {"results": [{"engines": ["bing news"]}]}
        self.assertEqual(self._err(sxq.report_foreign_engines, payload, "bing news"), "")

    def test_empty_time_range_result_is_explained(self):
        payload = {"results": [], "unresponsive_engines": []}
        err = self._err(sxq.report_empty_time_range, payload, "week")
        self.assertIn("time_range", err)

    def test_non_empty_time_range_result_is_quiet(self):
        payload = {"results": [{"engines": ["bing news"]}], "unresponsive_engines": []}
        self.assertEqual(self._err(sxq.report_empty_time_range, payload, "week"), "")
```

Run: `python3 -m unittest discover -s skills/searxng/tests -v` — expect `AttributeError` on both functions.

- [x] **Step 2: Implement** beside `report_unresponsive`:

```python
def report_foreign_engines(payload: dict, pinned: str) -> None:
    """SearXNG ignores an unknown or inactive engine name and runs the default
    search instead - measured 2026-10-15: engines='mojeek news' returned 96 rows
    from mwmbl, duckduckgo web and sii. Say so instead of letting it pass."""
    want = {e.strip() for e in pinned.split(",") if e.strip()}
    got = {e for r in payload.get("results", []) for e in (r.get("engines") or [])}
    foreign = sorted(got - want)
    if foreign:
        print(f"\n!! results came from engines you did not pin: {', '.join(foreign)}", file=sys.stderr)
        print(f"   {', '.join(sorted(want - got)) or 'the pinned engine'} is probably not loaded "
              "(inactive or misspelt) - check `sxq --health`.", file=sys.stderr)


def report_empty_time_range(payload: dict, time_range: str) -> None:
    """An engine without time_range_support is dropped when a range is set, so
    an empty, error-free answer can mean no engine ran at all."""
    if time_range and not payload.get("results") and not payload.get("unresponsive_engines"):
        print(f"\n!! empty with time_range={time_range} and no failing engine: probably no selected "
              "engine supports time_range. Retry without --time-range and filter by date.", file=sys.stderr)
```

Call both from `main()` after a search, guarded by `args.engines` / `args.time_range`.

- [x] **Step 3: Run the tests (pass), then the live checks**

```bash
python3 -m unittest discover -s skills/searxng/tests -v
skills/searxng/scripts/sxq test -e 'mojeek news' -n 1      # stderr names mwmbl/...
skills/searxng/scripts/sxq ECB -c news --time-range week -n 3  # results (after Task 4), no warning
```

- [x] **Step 4: Wire the tests into a target** — add `skill.test` to the `skill.*` group in `manage`/`Makefile` (next to `skill.check`, same skip-free behaviour: it needs only python3), and run it from `.github/workflows/skills.yml`.

- [x] **Step 5: Sync and validate the skill**

```bash
make skill.sync && make skill.check && make skill.validate
```

- [x] **Step 6: Commit**

```bash
git add skills/searxng manage Makefile .github/workflows/skills.yml
git commit -m "Warn in sxq when a pin or a time range silently changes the search"
```

---

### Task 6: Postman negative controls (D7)

**Files:**
- Modify: `postman/searxng-integration-test.postman_collection.json`

- [x] **Step 1: Add requests** in the `Fork engine: sii (sii.org.pl)` folder and the news folder:

| Request | Query | Test script asserts |
|---|---|---|
| `SII: one matching word of two is not a match (zzqxv term)` | `q=zzqxv term&engines=sii&format=json` | `results.length === 0`, `unresponsive_engines` contains no `sii` crash (a 429 is the accepted second outcome, as for the other SII requests) |
| `News with a time range runs an engine` | `q=ECB interest rate&categories=news&time_range=week&format=json` | `results.length > 0`; at least one result with `engine === "bing news"` |

Tighten `SII: multi-word company name (cd projekt)`: every result's `title + content`, lower-cased, contains `cd` and `projekt`.

- [x] **Step 2: Run** `./postman/run.sh --folder "Fork engine: sii (sii.org.pl)"` and the news folder. Expected: green (or the documented 429 outcome for SII bursts).

- [x] **Step 3: Mutation check** — temporarily set `bing news` back to `disabled: true`, restart, run the news folder, confirm it fails; restore and restart.

- [x] **Step 4: Commit**

```bash
git add postman/searxng-integration-test.postman_collection.json
git commit -m "Add Postman controls for sii term matching and news time ranges"
```

---

### Task 7: Documentation

**Files:**
- Modify: `DESIGN.md` (Local deployment), `skills/searxng/SKILL.md`, `skills/searxng/references/categories.md`

- [x] **Step 1:** `DESIGN.md` — under Local deployment, add: the `sii` all-terms filter and why; that `bing news` is the only time-range-capable news engine and what a block looks like; that pinning an unloaded engine falls back silently and `sxq` now says so.
- [x] **Step 2:** `SKILL.md` — replace "`--time-range` with `-c news` returns zero, silently" with the new behaviour (works through `bing news`; `sxq` warns when it does not). Add: "a `sii` hit contains every query term in its title or teaser".
- [x] **Step 3:** `make skill.sync && make skill.check && make skill.validate && make test.rst`
- [x] **Step 4: Commit**

```bash
git add DESIGN.md skills/searxng
git commit -m "Document sii term matching and the news time-range engine"
```

---

### Task 8: Full verification

- [x] `make test` — green (yamllint, black, pyright_modified, pylint, unit, robot, rst, shell, shfmt). — **green, `make test` exits 0.** Reaching that needed two host fixes and one repo fix, none of them this plan's: a plain Firefox under `local/firefox` (Ubuntu's `/usr/bin/firefox` is a snap shim, which selenium probes successfully and then hands to geckodriver, which execs and fails), `shellcheck` on the ambient PATH, and `gecko.driver` checking the driver it installed rather than whatever is on PATH. See DESIGN.md → Local deployment.
- [x] `./postman/run.sh` — green, SII 429 accepted as documented.
- [x] `git log --oneline -8` shows one commit per task 1, 2, 4, 5, 6, 7, and nothing else. — **done, with four extra commits.** One per task as specified, plus: two carry the Task 0 re-measurement into the spec and the `enable_http3` finding into D5; one brings the fork's own files back under black/pylint, which were already red before this plan started; one ends two test-settings files with a newline, which yamllint already rejected.
- [x] Notify the portfolio board: `idea.md` (Idea 4) "Found while probing: `sii`…" can cite the commit that fixed it; the lane's own guard stays (defence in depth). — **done.** `/opt/projects/kanban`, `boards/portfolio-engineering/idea.md`, commit `ebf33d8`: the section is marked fixed, cites `e18590129`, records the re-measurement, and states the accepted cost (a synonym miss is now dropped; `dropped N of M` is debug-only) and that the lane's own guard stays as defence in depth.
