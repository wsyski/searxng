# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,missing-class-docstring
"""Tests for the two silent-failure diagnostics in `scripts/sxq`.

Stdlib ``unittest`` on purpose: `sxq` is stdlib-only and the target that runs
this (`make skill.test`) must work on a bare python3, with no venv and no
`nose2` - the same reasoning as skill.check, which needs only `diff`.

Run: ``python3 -m unittest discover -s skills/searxng/tests -v``.

Each diagnostic exists because the failure it names is INVISIBLE in the output.
SearXNG ignores an engine name it cannot load and runs the default search
instead, so pinning `mojeek news` returns rows from engines nobody asked for;
and it drops every engine without `time_range_support` when a range is set, so
a ranged query can run zero engines and answer with an empty result and an empty
`unresponsive_engines`. Both look like a healthy answer.

The `-c news --time-range` case is the shape, not a current measurement: on
2026-10-30 that query returns rows, because `bing news` does support a range.
The empty-range warning still covers any category whose engines all lack it.

`Answers` covers the opposite mistake — reading `.results` alone and calling an
answer "no results", which is how four live categories came to be recorded as
dead.
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("sxq", os.path.join(HERE, "..", "scripts", "sxq"))
_spec = importlib.util.spec_from_loader("sxq", _loader)
assert _spec is not None, "spec_from_loader returns None only for a loader it cannot use"
sxq = importlib.util.module_from_spec(_spec)
_loader.exec_module(sxq)  # load_module() is gone in current Pythons

# One response, reused: a pinned engine that SearXNG ignored, so the answer is
# somebody else's. This is the shape both of main()'s diagnostics exist for.
FOREIGN_PAYLOAD = {
    "results": [{"engines": ["mwmbl"]}, {"engines": ["sii"]}],
    "unresponsive_engines": [],
}


def run_main(argv, payload=None):
    """Run sxq's main() against a stubbed HTTP layer; return (stdout, stderr)."""
    # setattr/getattr rather than `sxq.fetch = ...`: sxq was loaded from a file
    # with no .py suffix, so the checker sees a plain ModuleType and will not
    # let a declared attribute be assigned.
    saved_argv, saved_fetch = sys.argv, getattr(sxq, "fetch")
    sys.argv = ["sxq"] + argv
    stub = dict(FOREIGN_PAYLOAD if payload is None else payload)
    setattr(sxq, "fetch", lambda url, timeout, origin: dict(stub))
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            sxq.main()
    finally:
        # Restore both: leaking the stub would make every later test in this
        # process believe it is talking to a network.
        sys.argv = saved_argv
        setattr(sxq, "fetch", saved_fetch)
    return out.getvalue(), err.getvalue()


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

    def test_a_pinned_engine_that_matched_nothing_is_not_called_inactive(self):
        """It matched nothing - that is not evidence it failed to load.

        Real shape: the pin was `sii,dna rynkow`, `ksiazak` answered instead of
        both, and `dna rynkow` simply had no card for the query. The warning
        about `ksiazak` is the finding; naming `dna rynkow` as "probably not
        loaded" is a cause this tool did not measure, and it sends the reader to
        `sxq --health` for a fault that is not there.
        """
        payload = {"results": [{"engines": ["sii", "ksiazak"]}]}
        err = self._err(sxq.report_foreign_engines, payload, "sii,dna rynkow")
        self.assertIn("ksiazak", err)
        self.assertIn("dna rynkow", err)
        self.assertNotIn("not loaded", err)

    def test_a_pin_that_returned_nothing_at_all_is_called_inactive(self):
        """The one case where "not loaded" IS the reading: no row carries any
        pinned engine, so none of them ran."""
        payload = {"results": [{"engines": ["mwmbl"]}]}
        err = self._err(sxq.report_foreign_engines, payload, "sii,dna rynkow")
        self.assertIn("not loaded", err)
        self.assertIn("sii", err)
        self.assertIn("dna rynkow", err)

    def test_empty_time_range_result_is_explained(self):
        payload = {"results": [], "unresponsive_engines": []}
        err = self._err(sxq.report_empty_time_range, payload, "week")
        self.assertIn("time_range", err)

    def test_non_empty_time_range_result_is_quiet(self):
        payload = {"results": [{"engines": ["bing news"]}], "unresponsive_engines": []}
        self.assertEqual(self._err(sxq.report_empty_time_range, payload, "week"), "")


class Wiring(unittest.TestCase):
    """That main() calls them at all.

    Every other test here exercises a function directly, which is exactly how a
    diagnostic can be written, tested, and never wired up. These drive main()
    itself against a stubbed response, because the failure they cover is a call
    that is simply absent — invisible to any test of the function.
    """

    def test_a_ignored_pin_warns_on_the_normal_path(self):
        _, err = run_main(["test", "-e", "mojeek news"])
        self.assertIn("you did not pin", err)

    def test_a_ignored_pin_warns_in_json_mode_too(self):
        """`--json` is the path a caller pipes into another tool, so it is the
        one where a silently wrong answer is least visible. Emitting the warning
        on stderr keeps stdout a clean JSON document and still says it."""
        out, err = run_main(["test", "-e", "mojeek news", "--json"])
        self.assertIn("you did not pin", err)
        # ... and stdout must stay parseable, or the fix costs the caller more
        # than the warning is worth.
        self.assertIn('"results"', out)
        json.loads(out)


if __name__ == "__main__":
    unittest.main()


class Answers(unittest.TestCase):
    """`.answers` is where answerer-style engines put everything.

    Reading `.results` alone made this script print "no results" for `weather`,
    `currency`, `define` and `translate` - and that reading was written into the
    repository as four dead categories. Every one of them answers. The bug was
    here, not in the instance.
    """

    def test_a_legacy_answer_prints(self):
        answer = {"engine": "currency", "answer": "100.0 EUR = 438.77 PLN"}
        self.assertEqual(sxq.answer_lines(answer), ["100.0 EUR = 438.77 PLN"])

    def test_a_weather_answer_prints_its_summary(self):
        answer = {"engine": "duckduckgo weather", "current": {"summary": "Warszawa: 6 °C, Partly cloudy"}}
        self.assertEqual(sxq.answer_lines(answer), ["Warszawa: 6 °C, Partly cloudy"])

    def test_a_dictionary_answer_prints_its_translations(self):
        answer = {
            "engine": "dictzone",
            "translations": [{"text": "dog : pies", "definitions": ["a domestic animal"]}],
        }
        self.assertEqual(sxq.answer_lines(answer), ["dog : pies", "  a domestic animal"])

    def test_a_definition_that_repeats_the_text_is_printed_once(self):
        """wordnik sets `text` to its own first definition. Printing both shows
        the same sentence twice, which reads like a parsing fault."""
        answer = {"engine": "wordnik", "translations": [{"text": "A happy accident.", "definitions": ["A happy accident.", "An instance of one."]}]}
        self.assertEqual(sxq.answer_lines(answer), ["A happy accident.", "  An instance of one."])

    def test_an_unknown_answer_shape_is_skipped_not_crashed(self):
        self.assertEqual(sxq.answer_lines({"engine": "future"}), [])

    def test_an_answer_only_response_is_not_called_empty(self):
        payload = {
            "results": [],
            "answers": [{"engine": "currency", "answer": "100.0 EUR = 438.77 PLN"}],
            "unresponsive_engines": [],
        }
        out, _ = run_main(["100 EUR to PLN"], payload)
        self.assertIn("438.77", out)
        self.assertNotIn("no results", out)

    def test_a_genuinely_empty_response_still_says_so(self):
        payload = {"results": [], "answers": [], "unresponsive_engines": []}
        out, _ = run_main(["laptop", "-c", "shopping"], payload)
        self.assertIn("no results", out)


class ServerSideDiagnostics(unittest.TestCase):
    """The instance now states both of these itself, so the tool stops guessing."""

    def _err(self, fn, *a):
        buf = io.StringIO()
        with redirect_stderr(buf):
            fn(*a)
        return buf.getvalue()

    def test_unknown_engines_from_the_response_is_reported(self):
        payload = {"results": [{"engines": ["mwmbl"]}], "unknown_engines": ["mojeek news"]}
        err = self._err(sxq.report_ignored_pins, payload, "mojeek news")
        self.assertIn("mojeek news", err)
        self.assertIn("DEFAULT search", err)

    def test_no_unknown_engines_means_the_inference_still_runs(self):
        payload = {"results": [{"engines": ["mwmbl"]}], "unknown_engines": []}
        self.assertEqual(self._err(sxq.report_ignored_pins, payload, "mojeek news"), "")

    def test_an_instance_without_the_field_falls_back(self):
        """The field is a fork addition; a stock instance has no such key and the
        tool must still warn rather than go quiet."""
        _, err = run_main(["test", "-e", "mojeek news"], {"results": [{"engines": ["mwmbl"]}]})
        self.assertIn("you did not pin", err)

    def test_the_server_answer_replaces_the_inference(self):
        payload = {"results": [{"engines": ["mwmbl"]}], "unknown_engines": ["mojeek news"]}
        _, err = run_main(["test", "-e", "mojeek news"], payload)
        self.assertIn("no engine named", err)
        self.assertNotIn("you did not pin", err)

    def test_a_drop_count_is_reported(self):
        payload = {"engine_data": {"sii": {"dropped_rows": "7", "site_rows": "10"}}}
        err = self._err(sxq.report_engine_data, payload)
        self.assertIn("sii dropped 7 of 10", err)

    def test_nothing_dropped_is_quiet(self):
        payload = {"engine_data": {"sii": {"dropped_rows": "0", "site_rows": "3"}}}
        self.assertEqual(self._err(sxq.report_engine_data, payload), "")

    def test_the_drop_count_is_wired_into_main(self):
        payload = {
            "results": [],
            "answers": [],
            "unresponsive_engines": [],
            "engine_data": {"sii": {"dropped_rows": "10", "site_rows": "10"}},
        }
        _, err = run_main(["pkn", "-e", "sii"], payload)
        self.assertIn("sii dropped 10 of 10", err)
