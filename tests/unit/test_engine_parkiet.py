# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name,protected-access

"""Tests for the Parkiet (parkiet.com) search engine.

Pinned behaviours, all measured on the live site 2026-11-08:

- the visible page is a shell whose container is EMPTY; the rows come from
  the same URL with ``?ajax=1``, which answers JSON ``{html, isLoadMore}``.
  The engine must parse the fragment out of that JSON, not the page.
- the term is a PATH segment (``/szukaj/<terms>``); the query form
  ``/szukaj?q=...`` 301s to ``/`` and can never yield rows.
- no matches is an empty fragment with ``isLoadMore: 0`` — zero results.
- a non-JSON answer (the shell, an error page) is an engine failure, not an
  empty result set.
"""

import json
import typing as t
from datetime import datetime
from unittest.mock import Mock

import searx.engines
from searx.exceptions import SearxEngineResponseException
from searx.result_types import LegacyResult
from searx.search.processors import OnlineParamTypes
from tests import SearxTestCase


def _params(**extra: t.Any) -> OnlineParamTypes:
    base: dict[str, t.Any] = {"headers": {}}
    base.update(extra)
    return t.cast(OnlineParamTypes, t.cast(object, base))


def _url(params: OnlineParamTypes) -> str:
    return params.get("url") or ""


def _resp(payload, status_code=200):
    r = Mock()
    r.text = payload if isinstance(payload, str) else json.dumps(payload)
    r.status_code = status_code
    return r


# Real markup, trimmed from the ajax fragment: one content--block per row —
# overline date, title anchor to /section/art<id>-slug, teaser paragraph.
FRAGMENT = """\
<div class="row">
<div data-mrf-placement="1" class="row content--block -small">
<div class="md:w-54"><a data-gtm-trigger="image" href="/gielda/art45457261-wyprzedaz" class="contentLink placement--img"><picture></picture></a></div>
<div class="col--fill">
<div class="overline--comp pb-1"> 17:43 - 06.11.2026 </div>
<a data-gtm-trigger="title" class="contentLink !line-clamp-4" href="/gielda/art45457261-wyprzedaz-spolek-z-sektora-ai" >
<h2 class="t--60"> Wyprzedaz spolek z sektora AI zatrziesla rynkami </h2>
</a>
<p class="teaser--lead lead--30"> Potzna przecena w USA i Azji napedzila strachu inwestorom. </p>
</div>
</div>
<div data-mrf-placement="2" class="row content--block -small">
<div class="col--fill">
<div class="overline--comp pb-1"> 09:10 - 05.11.2026 </div>
<a data-gtm-trigger="title" class="contentLink" href="/biura-maklerskie/art45455691-trzy-zlote-dekady" >
<h2 class="t--60"> Trzy zlote dekady izby domow maklerskich </h2>
</a>
<p class="teaser--lead lead--30"> Historia izby. </p>
</div>
</div>
</div>
"""


class ParkietEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_parkiet.yml"

    def setUp(self):
        super().setUp()
        self.engine = t.cast(t.Any, searx.engines.engines["parkiet"])

    def test_request_puts_the_term_in_the_path_with_the_ajax_flag(self):
        params = _params()
        self.engine.request("KGHM", params)
        self.assertIn("/szukaj/KGHM?", _url(params))
        self.assertIn("ajax=1", _url(params))
        self.assertNotIn("?q=", _url(params))

    def test_request_percent_encodes_spaces(self):
        params = _params()
        self.engine.request("cyfrowy polsat", params)
        self.assertIn("/szukaj/cyfrowy%20polsat?", _url(params))

    def test_request_carries_the_page_number(self):
        params = _params(pageno=2)
        self.engine.request("KGHM", params)
        self.assertIn("page=2", _url(params))

    def test_paging_is_enabled(self):
        self.assertTrue(self.engine.paging)

    def test_the_category_is_finance_poland(self):
        self.assertEqual(self.engine.categories, ["finance", "finance poland"])

    def test_response_parses_the_json_fragment(self):
        results = self.engine.response(_resp({"html": FRAGMENT, "isLoadMore": 1}))
        self.assertEqual(len(results), 2)
        first = t.cast(LegacyResult, list(results)[0])
        self.assertEqual(first["url"], "https://www.parkiet.com/gielda/art45457261-wyprzedaz-spolek-z-sektora-ai")
        self.assertEqual(first["title"], "Wyprzedaz spolek z sektora AI zatrziesla rynkami")
        self.assertEqual(first["publishedDate"], datetime(2026, 11, 6, 17, 43))
        self.assertEqual(first["content"], "Potzna przecena w USA i Azji napedzila strachu inwestorom.")

    def test_no_matches_is_zero_results(self):
        self.assertEqual(len(self.engine.response(_resp({"html": " ", "isLoadMore": 0}))), 0)

    def test_the_shell_page_is_a_failure_not_an_empty_result(self):
        # The non-ajax answer is HTML, not the ajax JSON; reporting it as
        # "zero results" would hide a broken URL form.
        with self.assertRaises(SearxEngineResponseException):
            self.engine.response(_resp("<html><body><div class='loadMoreContainerAppend'></div></body></html>"))

    def test_an_unexpected_status_is_a_response_exception(self):
        with self.assertRaises(SearxEngineResponseException):
            self.engine.response(_resp("<html>boom</html>", status_code=404))
