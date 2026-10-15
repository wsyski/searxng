# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,missing-class-docstring
"""Tests for the two silent-failure diagnostics in `scripts/sxq`.

Stdlib ``unittest`` on purpose: `sxq` is stdlib-only and the target that runs
this (`make skill.test`) must work on a bare python3, with no venv and no
`nose2` - the same reasoning as skill.check, which needs only `diff`.

Run: ``python3 -m unittest discover -s skills/searxng/tests -v``.

Both diagnostics exist because the failure they name is INVISIBLE in the output.
SearXNG ignores an engine name it cannot load and runs the default search
instead, so pinning `mojeek news` returns 96 rows from mwmbl, duckduckgo web
and sii; and it drops every engine without `time_range_support` when a range is
set, so `-c news --time-range week` returns nothing with an empty
`unresponsive_engines`. Both look like a healthy answer.
"""

import importlib.machinery
import importlib.util
import io
import os
import unittest
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("sxq", os.path.join(HERE, "..", "scripts", "sxq"))
_spec = importlib.util.spec_from_loader("sxq", _loader)
assert _spec is not None, "spec_from_loader returns None only for a loader it cannot use"
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


if __name__ == "__main__":
    unittest.main()