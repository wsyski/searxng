# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name
"""Tests for the SII (sii.org.pl) engine.

Every assertion here pins something that was measured on the live site on
2026-10-11 and that a future edit can silently break without failing
anything else. The two that matter most:

- the query parameter is ``search`` and not ``q``. ``?q=`` returns HTTP 200
  and an identical 62,576-byte page for *every* query, including a nonsense
  one, so the wrong parameter produces a healthy engine with no results.
- a query matching nothing answers **404**, not an empty 200. Without
  ``raise_for_httperror = False`` that surfaces as a broken engine.
"""

from datetime import datetime
from unittest.mock import Mock

import searx.engines
from searx import webutils
from searx.exceptions import (
    SearxEngineAccessDeniedException,
    SearxEngineResponseException,
    SearxEngineTooManyRequestsException,
)
from tests import SearxTestCase

# A result block in the site's "comment" variant: the date/author line is
# <p class="above metas"> — TWO classes on one element — and the summary is
# <p class="above">.
COMMENT_BLOCK = """
<div class="newsabout">
<h3 class="above">
<a href="https://www.sii.org.pl/19419/analizy/komentarze-at/spolka-tygodnia-orlen.html"
   title="Spółka tygodnia: ORLEN">Spółka tygodnia: ORLEN</a>
</h3>
<p class="above metas"><span class="calendar"></span>09.10.2026 &nbsp; <br>
<span class="author"></span><a href="https://www.sii.org.pl/autor/janusz-grabowski.html">Janusz Grabowski</a></p>
<p class="above">Korekta po realizacji zysków i próba odbicia.<a href="https://www.sii.org.pl/19419/x.html"><span>Zobacz&nbsp;więcej</span></a></p>
</div>
"""

# The "news" variant: metas on its own, summary in <p class="notes">.
NEWS_BLOCK = """
<div class="newsabout">
<h3 class="above">
<a href="https://www.sii.org.pl/19384/ochrona-praw/orlen-energa.html"
   title="Orlen, Energa i przymusowy wykup">Orlen, Energa i przymusowy wykup</a>
</h3>
<p class="metas"><span class="calendar"></span>02.10.2026 &nbsp; <a href="https://www.sii.org.pl/autor/michal.html">Michal Z</a></p>
<p class="notes">Przymusowy wykup akcji Energi zamyka pewien etap.</p>
</div>
"""

# An advert, interleaved in the same page, and an author link, which share
# the block but are not results.
AD_AND_AUTHOR = """
<div class="mustsee right"><div class="adshold">
<a class="clicky cf" href="https://www.sii.org.pl/click.php?rid=1635" title="forfin-zapisy">reklama</a>
</div></div>
<a href="https://www.sii.org.pl/autor/janusz-grabowski.html">Janusz Grabowski</a>
"""

EMPTY_SHELL = (
    "<html><body><div class='wrapup'></div></body></html>"  # 5.4 kB, 0 results
)


def _resp(text, status_code=200):
    r = Mock()
    r.text = text
    r.status_code = status_code
    return r


class SiiEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_sii.yml"

    def setUp(self):
        super().setUp()
        self.engine = searx.engines.engines["sii"]

    # -- the query parameter -------------------------------------------------

    def test_request_uses_search_not_q(self):
        params = {"headers": {}}
        self.engine.request("orlen", params)
        self.assertIn("search=orlen", params["url"])
        self.assertNotIn("?q=", params["url"])
        self.assertNotIn("&q=", params["url"])

    def test_request_opts_out_of_raise_for_httperror(self):
        """Without this a zero-hit query is a 404 and looks like a dead engine."""
        params = {"headers": {}}
        self.engine.request("nothing", params)
        self.assertFalse(params["raise_for_httperror"])

    def test_request_identifies_as_searxng(self):
        params = {"headers": {}}
        self.engine.request("orlen", params)
        self.assertEqual(params["headers"]["User-Agent"], "SearXNG/1.0")

    # -- status handling -----------------------------------------------------

    def test_a_404_is_an_empty_result_not_a_failure(self):
        results = self.engine.response(_resp("", status_code=404))
        self.assertEqual(len(results), 0)

    def test_any_other_error_status_still_raises(self):
        """404 is special. A 500 must not be swallowed into 'no results'."""
        for code in (500, 503):
            with self.assertRaises(SearxEngineResponseException):
                self.engine.response(_resp("", status_code=code))

    def test_a_429_is_reported_as_throttling_not_as_a_crash(self):
        """Measured 2026-10-11: a burst of eight searches got 429 after two.

        The generic response exception made SearXNG label this "unexpected
        crash", which is the opposite of what happened - the site rate-limited
        us and the engine correctly reported it. The dedicated exception also
        SUSPENDS the engine for an hour, so the burst is not repeated.
        """
        with self.assertRaises(SearxEngineTooManyRequestsException):
            self.engine.response(_resp("", status_code=429))

    def test_a_403_is_reported_as_access_denied(self):
        """What the site returns for a degenerate User-Agent - our fault, not a block."""
        with self.assertRaises(SearxEngineAccessDeniedException):
            self.engine.response(_resp("", status_code=403))

    def test_the_throttle_exception_renders_as_a_readable_label(self):
        """webutils maps exception class names to user-facing text; an unmapped
        class falls back to "unexpected crash", which is what the first version
        of this engine produced."""
        label = webutils.exception_classname_to_text.get(
            "searx.exceptions.SearxEngineTooManyRequestsException"
        )
        self.assertIsNotNone(label)
        self.assertNotEqual(label, "unexpected crash")

    def test_an_empty_shell_parses_to_nothing(self):
        self.assertEqual(len(self.engine.response(_resp(EMPTY_SHELL))), 0)

    # -- parsing -------------------------------------------------------------

    def test_both_markup_variants_yield_a_summary(self):
        for block in (COMMENT_BLOCK, NEWS_BLOCK):
            results = self.engine.response(_resp(block))
            self.assertEqual(len(results), 1, block[:60])
            self.assertTrue(
                results[0].content.strip(), f"no summary parsed from {block[:60]}"
            )

    def test_the_date_line_is_never_the_summary(self):
        """One variant writes it as class="above metas" — two classes, one element."""
        results = self.engine.response(_resp(COMMENT_BLOCK))
        self.assertNotIn("09.10.2026", results[0].content)
        self.assertNotIn("Janusz", results[0].content)

    def test_the_more_link_is_stripped(self):
        results = self.engine.response(_resp(COMMENT_BLOCK))
        self.assertNotIn("Zobacz", results[0].content)

    def test_the_date_is_parsed(self):
        results = self.engine.response(_resp(COMMENT_BLOCK))
        self.assertEqual(results[0].publishedDate, datetime(2026, 10, 9))

    def test_an_impossible_date_is_dropped_not_raised(self):
        block = COMMENT_BLOCK.replace("09.10.2026", "31.02.2026")
        results = self.engine.response(_resp(block))
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].publishedDate)

    def test_adverts_are_not_results(self):
        self.assertEqual(len(self.engine.response(_resp(AD_AND_AUTHOR))), 0)

    def test_duplicate_urls_appear_once(self):
        results = self.engine.response(_resp(COMMENT_BLOCK + COMMENT_BLOCK))
        self.assertEqual(len(results), 1)

    def test_two_variants_together_do_not_bleed_into_each_other(self):
        results = self.engine.response(_resp(COMMENT_BLOCK + NEWS_BLOCK))
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(r.content.strip())
            self.assertNotIn("&nbsp;", r.content)

    def test_paging_is_disabled(self):
        """strona=2 returns byte-identical output, so offering it would break."""
        self.assertFalse(self.engine.paging)

    def test_the_engine_is_news_only(self):
        self.assertEqual(self.engine.categories, ["news", "general"])
