# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name,protected-access

"""Tests for the Bankier (bankier.pl) full-text news search engine.

Pinned behaviours, all measured on the live site 2026-11-08:

- the parameter is ``qt``, NOT ``q``: a wrong parameter answers 200 with one
  identical no-results page, which reads as "healthy, found nothing".
- a query with no matches is 200 + ``Znaleziono: 0`` + no article rows, so
  zero results needs no special case in ``response``.
- rows carry an ISO ``datetime`` attribute with offset; the engine parses it
  with ``fromisoformat`` rather than the displayed text.
"""

import typing as t
from datetime import datetime, timedelta, timezone
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


def _resp(text, status_code=200):
    r = Mock()
    r.text = text
    r.status_code = status_code
    return r


# Real markup, trimmed: title anchor in entry-title, offset-bearing time
# attribute, teaser paragraph in entry-content.
ROWS = """\
<article class="article hentry" itemscope itemtype="">
    <header class="entry-header">
        <h2 class="entry-title">
            <a href="/wiadomosc/Bitcoin-za-milion-dolarow-9225023.html" title="" rel="bookmark">Bitcoin za milion dolarow</a>
        </h2>
        <div class="entry-meta">
            <time class="entry-date" datetime="2026-11-07T06:00:00+01:00" pubdate>2026-11-07 06:00</time>
        </div>
    </header>
    <div class="entry-content">
        <a class="photo" href="/wiadomosc/Bitcoin-za-milion-dolarow-9225023.html"><img src="https://galeria.bankier.pl/p/x.jpg" alt=""></a>
        <p>Kiedy kurs bitcoina przebije znow 100 tys. dolarow?</p>
    </div>
</article>
<article class="article hentry" itemscope itemtype="">
    <header class="entry-header">
        <h2 class="entry-title">
            <a href="/wiadomosc/KGHM-drugi-9222593.html" title="" rel="bookmark">KGHM drozeje</a>
        </h2>
        <div class="entry-meta">
            <time class="entry-date" datetime="2026-11-05T16:30:00+01:00" pubdate>2026-11-05 16:30</time>
        </div>
    </header>
    <div class="entry-content"><p>Miedz traci.</p></div>
</article>
"""

RESULTS_PAGE = f"<html><body><section id='searchResult'>{ROWS}</section></body></html>"

EMPTY_PAGE = """\
<html><body>
<div id="searchCount">Znaleziono: <strong>0</strong> wynik&oacute;w</div>
<section class="section" id="searchResult"></section>
<p>Nie znaleziono wynikow dla Twojego zapytania.</p>
</body></html>
"""


class BankierEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_bankier.yml"

    def setUp(self):
        super().setUp()
        self.engine = t.cast(t.Any, searx.engines.engines["bankier"])

    def test_request_uses_the_qt_parameter(self):
        params = _params()
        self.engine.request("KGHM", params)
        self.assertIn("qt=KGHM", _url(params))
        self.assertIn("page=1", _url(params))

    def test_request_carries_the_page_number(self):
        params = _params(pageno=4)
        self.engine.request("KGHM", params)
        self.assertIn("page=4", _url(params))

    def test_request_encodes_reserved_characters(self):
        params = _params()
        self.engine.request("AT&T", params)
        self.assertIn("qt=AT%26T", _url(params))

    def test_paging_is_enabled(self):
        self.assertTrue(self.engine.paging)

    def test_the_category_is_finance_poland(self):
        self.assertEqual(self.engine.categories, ["finance", "finance poland"])

    def test_response_parses_absolute_urls_iso_dates_and_teasers(self):
        results = self.engine.response(_resp(RESULTS_PAGE))
        self.assertEqual(len(results), 2)
        first = t.cast(LegacyResult, list(results)[0])
        self.assertEqual(first["url"], "https://www.bankier.pl/wiadomosc/Bitcoin-za-milion-dolarow-9225023.html")
        self.assertEqual(first["publishedDate"], datetime(2026, 11, 7, 6, 0, tzinfo=timezone(timedelta(hours=1))))
        self.assertEqual(first["content"], "Kiedy kurs bitcoina przebije znow 100 tys. dolarow?")

    def test_the_empty_state_is_zero_results(self):
        self.assertEqual(len(self.engine.response(_resp(EMPTY_PAGE))), 0)

    def test_an_unexpected_status_is_a_response_exception(self):
        with self.assertRaises(SearxEngineResponseException):
            self.engine.response(_resp("<html>boom</html>", status_code=500))


class BankierParameterTrap(SearxTestCase):
    """The ignored-parameter page must not look like a searched page."""

    TEST_SETTINGS = "test_bankier.yml"

    def setUp(self):
        super().setUp()
        self.engine = t.cast(t.Any, searx.engines.engines["bankier"])

    def test_wrong_parameter_page_yields_zero_not_fake_rows(self):
        # The 31,450-byte ignored-parameter page has no <article> at all;
        # parsing it must give zero results rather than inventing rows.
        wrong_param_page = "<html><body><form action='/wyszukiwarka' method='get'></form></body></html>"
        self.assertEqual(len(self.engine.response(_resp(wrong_param_page))), 0)
