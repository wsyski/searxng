# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name,protected-access

"""Tests for the Stooq (stooq.com) news engine.

The source is a news index, not an instrument search, and three behaviours cost
real time to establish — each is pinned here so a future edit fails loudly:

- the search page is behind a SHA-256 proof-of-work gate and a Google consent
  wall. ``robots.txt`` disallows the engine, which is why it is disabled by
  default; the gate is solved, deliberately, only for opt-in calls.
- a UA of any kind gets the same 795-byte challenge, so the engine sets none.
  ``request`` must not grow a pretend-browser header to "fix" this.
- a query with no matches is HTTP 200 plus an explicit Polish empty state, while
  the consent document carries neither of the two real-page markers. Parsing
  one as the other reports zero results for a wall, or a wall for a miss.
"""

import hashlib
from datetime import datetime
from typing import Any, cast
from unittest.mock import Mock, patch

import searx.engines
from searx.exceptions import (
    SearxEngineCaptchaException,
    SearxEngineResponseException,
    SearxEngineTooManyRequestsException,
)
from searx.result_types import LegacyResult
from searx.search.processors import OnlineParamTypes
from tests import SearxTestCase


def _rows(results):
    """Every row, narrowed to what this engine actually builds."""
    return [cast(LegacyResult, r) for r in results]


def _first(results):
    return _rows(results)[0]


def _params(**extra: Any) -> OnlineParamTypes:
    """A request-params dict as the online processor builds it."""
    base: dict[str, Any] = {"headers": {}}
    base.update(extra)
    return cast(OnlineParamTypes, cast(object, base))


def _url(params: OnlineParamTypes) -> str:
    return params.get("url") or ""


def _resp(text, status_code=200):
    r = Mock()
    r.text = text
    r.status_code = status_code
    return r


# Real markup, trimmed: unquoted attributes, title in <font id=f16>, teaser and
# the `date - PAP` span in the <font id=f13> that follows the same <br>.
ROWS = """\
<font id=f16><a href=n/?f=1733372&search=cdprojekt>Zestawienie udziału OFE w kapitale spółek z GPW na koniec 2025 r.</a></font><br>
<font id=f13><b>...</b> CCENERGY 0,00%, <b class=hs1>CDPROJEKT</b> 3,72% 0,19% 5,83%, <b>...</b><br>
<span class=lc1>20 sty 2026, 7:45 - PAP</span></font><br><br><br>
<font id=f16><a href=n/?f=1733366&search=cdprojekt>Zestawienie zaangażowania OFE w spółki z WIG20 na koniec 2025 r.</a></font><br>
<font id=f13><b>...</b> CDPROJEKT 4 191 837 188 17,37% -0,57, <b>...</b><br>
<span class=lc1>20 sty 2026, 7:30 - PAP</span></font><br><br><br>
"""

_PAGE = """\
<html><head><title>Wyszukiwarka - Stooq</title></head><body>
<div class=navigation><b>Szukaj na Stooq: cdprojekt</b> Wyniki: <b>1 - 10</b>
<a href=search/?q=cdprojekt&l=2>2</a> <a href=search/?q=cdprojekt&l=2>Następna ></a></div>
<table width=72% border=0 cellpadding=0 cellspacing=0><tr valign=top><td width=10></td><td>
__ROWS__
</td></tr></table>
</body></html>
"""

RESULTS_PAGE = _PAGE.replace("__ROWS__", ROWS)

EMPTY_PAGE = """\
<html><head><title>Wyszukiwarka - Stooq</title></head><body>
<div class=navigation><b>Szukaj na Stooq: zzzqqqxxnosuchterm</b></div>
<p>Nie znaleziono szukanego wyrażenia</p>
</body></html>
"""

CONSENT_PAGE = """\
<script>(async()=>{/* Google Funding Choices consent document, 234 kB in full */})();</script>
"""

# Shaped like the live challenge: c is arbitrary, d is the measured difficulty.
CHALLENGE = (
    "<!DOCTYPE html><html><body><noscript>This site requires JavaScript</noscript>"
    '<script>(async()=>{const c="AAAAAGrc2N8RqLwDurSmnYB3Fo",d=4,t="0".repeat(d);'
    'while(1){const h=await crypto.subtle.digest("SHA-256",c+n);if(h.startsWith(t))break;n++}'
    'fetch("/__verify",{method:"POST",body:"c="+c+"&n="+n})})();</script></body></html>'
)


class StooqEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_stooq.yml"

    def setUp(self):
        super().setUp()
        # The registry types every entry as the ``Engine`` protocol, which does
        # not carry module-level functions (``_solve_pow``) or the engine cache.
        self.engine = cast(Any, searx.engines.engines["stooq"])

    # -- the query interface -------------------------------------------------

    def test_request_targets_the_news_search(self):
        params = _params()
        self.engine.request("cdprojekt", params)
        self.assertIn("/search/?q=cdprojekt", _url(params))
        self.assertIn("type=nws", _url(params), "the Wiadomości scope, not whole-site fll")
        # Ticker lookup is /q/s/ and is not this source.
        self.assertNotIn("/q/s/", _url(params))

    def test_request_carries_the_page_number(self):
        params = _params()
        self.engine.request("cdprojekt", params)
        self.assertIn("l=1", _url(params))
        params = _params(pageno=3)
        self.engine.request("cdprojekt", params)
        self.assertIn("l=3", _url(params))

    def test_request_encodes_reserved_characters(self):
        params = _params(pageno=2)
        self.engine.request("AT&T", params)
        self.assertIn("q=AT%26T", _url(params))
        self.assertTrue(_url(params).endswith("&l=2&type=nws"))

    def test_request_sets_the_consent_cookie_and_never_a_user_agent(self):
        params = _params()
        with patch.object(self.engine.CACHE, "get", return_value=None):
            self.engine.request("cdprojekt", params)
        self.assertEqual(params["cookies"]["privacy"], "1")
        self.assertNotIn("auth", params["cookies"])
        # Every UA gets the same challenge; a browser UA would only be a lie.
        self.assertEqual(params["headers"], {})

    def test_request_replays_a_cached_auth_cookie(self):
        params = _params()
        with patch.object(self.engine.CACHE, "get", return_value="tok"):
            self.engine.request("cdprojekt", params)
        self.assertEqual(params["cookies"]["auth"], "tok")
        self.assertEqual(params["cookies"]["privacy"], "1")

    def test_paging_is_enabled(self):
        self.assertTrue(self.engine.paging)

    def test_the_category_is_finance_only(self):
        self.assertEqual(self.engine.categories, ["finance", "finance poland"])

    # -- the proof-of-work gate ----------------------------------------------

    def test_the_pow_solution_is_replayed_to_verify(self):
        posted = {}

        def fake_post(url, data=None):
            posted["url"] = url
            posted["data"] = data
            return Mock(cookies={"auth": "tok"})

        with patch.object(self.engine, "post", side_effect=fake_post), patch.object(self.engine.CACHE, "set"):
            auth = self.engine._solve_pow(_resp(CHALLENGE))

        self.assertEqual(auth, "tok")
        self.assertTrue(posted["url"].endswith("/__verify"))
        digest = hashlib.sha256((posted["data"]["c"] + str(posted["data"]["n"])).encode()).hexdigest()
        self.assertTrue(digest.startswith("0000"))

    def test_a_missing_auth_cookie_is_a_captcha_not_a_silent_empty(self):
        with patch.object(self.engine, "post", return_value=Mock(cookies={})), patch.object(self.engine.CACHE, "set"):
            with self.assertRaises(SearxEngineCaptchaException):
                self.engine._solve_pow(_resp(CHALLENGE))

    def test_a_stale_cookie_is_re_solved_once_in_response(self):
        resp = _resp(CHALLENGE)
        resp.search_params = _params(url="https://stooq.com/search/?q=cdprojekt", cookies={})
        with (
            patch.object(self.engine, "post", return_value=Mock(cookies={"auth": "new"})),
            patch.object(self.engine, "get", return_value=_resp(RESULTS_PAGE)) as retry,
            patch.object(self.engine.CACHE, "set"),
        ):
            results = self.engine.response(resp)

        self.assertEqual(len(results), 2)
        self.assertEqual(retry.call_args.kwargs["cookies"]["auth"], "new")

    def test_the_consent_wall_is_a_captcha_not_an_empty_result(self):
        with self.assertRaises(SearxEngineCaptchaException):
            self.engine.response(_resp(CONSENT_PAGE))

    # -- parsing -------------------------------------------------------------

    def test_a_row_yields_url_title_snippet_and_date(self):
        results = self.engine.response(_resp(RESULTS_PAGE))
        self.assertEqual(len(results), 2)
        r = _first(results)
        self.assertEqual(r.url, "https://stooq.com/n/?f=1733372&search=cdprojekt")
        self.assertIn("Zestawienie udziału OFE", r.title)
        self.assertIn("CDPROJEKT", r.content)
        self.assertNotIn("PAP", r.content, "the date line is not part of the snippet")
        self.assertEqual(r.publishedDate, datetime(2026, 1, 20, 7, 45))

    def test_every_polish_month_abbreviation_resolves(self):
        for abbr, month in [
            ("sty", 1),
            ("lut", 2),
            ("mar", 3),
            ("kwi", 4),
            ("maj", 5),
            ("cze", 6),
            ("lip", 7),
            ("sie", 8),
            ("wrz", 9),
            ("paź", 10),
            ("lis", 11),
            ("gru", 12),
        ]:
            page = RESULTS_PAGE.replace("20 sty 2026", f"20 {abbr} 2026")
            self.assertEqual(
                _first(self.engine.response(_resp(page))).publishedDate,
                datetime(2026, month, 20, 7, 45),
                abbr,
            )

    def test_an_explicitly_empty_page_yields_nothing(self):
        self.assertEqual(len(self.engine.response(_resp(EMPTY_PAGE))), 0)

    def test_duplicate_rows_appear_once(self):
        self.assertEqual(len(self.engine.response(_resp(_PAGE.replace("__ROWS__", ROWS + ROWS)))), 2)

    def test_a_non_200_status_raises(self):
        for code in (403, 500):
            with self.assertRaises(SearxEngineResponseException):
                self.engine.response(_resp("", status_code=code))

    def test_429_is_reported_as_rate_limited(self):
        with self.assertRaises(SearxEngineTooManyRequestsException):
            self.engine.response(_resp("", status_code=429))
