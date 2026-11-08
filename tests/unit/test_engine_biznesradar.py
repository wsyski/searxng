# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name,protected-access

"""Tests for the Biznesradar (biznesradar.pl) per-company news engine.

Pinned behaviours, all measured on the live site 2026-11-08:

- pagination is the comma PATH form `<SLUG>,<n>`; `?page=` is silently
  ignored, so a query-param page reads as "page 2 works" while returning
  page 1 rows.
- the slug is case-sensitive, hence the upper-casing in ``request``.
- an unknown symbol is HTTP 404 and must report zero results, not a failure.
"""

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


def _resp(text, status_code=200):
    r = Mock()
    r.text = text
    r.status_code = status_code
    return r


# Real markup, trimmed: external article link in record-header, teaser in
# record-body, ISO-ish footer date. Two rows so cross-row matching bugs fail.
ROWS = """\
<div id="msg-1114554636" class="record record-type-NEWS">
    <div class="record-avatar"><img src="/gfx/logos/oid__36.jpg" alt="XYZ" /></div>
    <div class="record-header">
        <a target="_blank" href="https://xyz.pl/tylko-wig20/" rel="nofollow">Tylko WIG20 swiecil sie na zielono</a>
    </div>
    <div class="record-body">
        WIG20 nadal reaguje na wyborcze zwyciestwo. Najmocniej rosly spolki handlu detalicznego.
    </div>
    <div class="record-footer">
        <a target="_blank" class="record-author" href="https://xyz.pl/sekcja/biznes/" rel="nofollow">XYZ</a>
        <span>|</span>
        <span class="record-date">2026-11-05 17:56:13</span>
    </div>
</div>
<div id="msg-1114553999" class="record record-type-POST">
    <div class="record-avatar"><img src="/gfx/logos/oid__1.jpg" alt="BR" /></div>
    <div class="record-header">
        <a target="_blank" href="https://www.biznesradar.pl/wiadomosc/WIG20-rebound" rel="nofollow">WIG20 odbija</a>
    </div>
    <div class="record-body">Sesja w Warszawie na plusie.</div>
    <div class="record-footer">
        <span class="record-date">2026-11-04 09:12:00</span>
    </div>
</div>
"""

PAGE = f"<html><body><div id='news-radar-body'>{ROWS}</div></body></html>"


class BiznesradarEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_biznesradar.yml"

    def setUp(self):
        super().setUp()
        self.engine = t.cast(t.Any, searx.engines.engines["biznesradar"])

    def test_request_uppercases_the_slug_and_uses_the_path_page(self):
        params = _params()
        self.engine.request("orlen", params)
        self.assertIn("/wiadomosci/ORLEN,1", _url(params))

    def test_request_maps_spaces_to_hyphens(self):
        params = _params(pageno=3)
        self.engine.request("cyfrowy polsat", params)
        self.assertIn("/wiadomosci/CYFROWY-POLSAT,3", _url(params))

    def test_request_does_not_use_a_query_page(self):
        params = _params(pageno=2)
        self.engine.request("KGH", params)
        self.assertNotIn("?page=", _url(params))
        # The site's own pagination is path-only: `?page=` is ignored.
        self.assertTrue(_url(params).endswith("/wiadomosci/KGH,2"))

    def test_paging_is_enabled(self):
        self.assertTrue(self.engine.paging)

    def test_the_category_is_finance_poland(self):
        self.assertEqual(self.engine.categories, ["finance", "finance poland"])

    def test_response_parses_rows_dates_and_external_urls(self):
        results = self.engine.response(_resp(PAGE))
        self.assertEqual(len(results), 2)
        first = t.cast(LegacyResult, list(results)[0])
        self.assertEqual(first["url"], "https://xyz.pl/tylko-wig20/")
        self.assertEqual(first["title"], "Tylko WIG20 swiecil sie na zielono")
        self.assertEqual(first["publishedDate"], datetime(2026, 11, 5, 17, 56, 13))

    def test_an_unknown_symbol_is_zero_results_not_an_error(self):
        results = self.engine.response(_resp("<html>not found</html>", status_code=404))
        self.assertEqual(len(results), 0)

    def test_an_unexpected_status_is_a_response_exception(self):
        with self.assertRaises(SearxEngineResponseException):
            self.engine.response(_resp("<html>boom</html>", status_code=503))
