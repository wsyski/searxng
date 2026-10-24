# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name

"""Tests for the DNA Rynków (dnarynkow.pl) engine.

Every fixture here is the real markup, trimmed. Two findings are pinned that
cost real time to get wrong the first time:

- the search is a **parameter** on the stock index (``/spolki/?search=``), not a
  search page. There is no ``/szukaj``, no REST API and no sitemap entry for it,
  so every path-shaped probe returns 404 while the engine works fine.
- the result rows are server-rendered into the **HTML body**, not into the
  ``__NUXT_DATA__`` payload. The payload is ~2.5 kB and holds no stock data, so
  a payload-only check reports "client rendered, nothing here".

Plus the off-by-one: ``page=1`` and ``page=0`` both return the first page, so
the parameter is 1-based in effect even though 0 is accepted.
"""

from datetime import datetime
from typing import Any, cast
from unittest.mock import Mock

import searx.engines
from searx.exceptions import SearxEngineResponseException
from searx.result_types import LegacyResult
from searx.search.processors import OnlineParamTypes
from tests import SearxTestCase


def _rows(results):
    """Every row, narrowed to what this engine actually builds.

    ``EngineResults`` yields the base ``Result`` type, whose fields are the
    engine-agnostic ones; ``title``, ``content`` and ``publishedDate`` belong to
    ``LegacyResult``, which is what ``dnarynkow.response`` adds. Narrowing once
    here keeps the assertions below reading as assertions.
    """
    return [cast(LegacyResult, r) for r in results]


def _first(results):
    return _rows(results)[0]


def _params(**extra: Any) -> OnlineParamTypes:
    """A request-params dict as the online processor builds it.

    ``OnlineParams`` is a TypedDict in which every key is required, so a test
    that supplies only ``pageno`` cannot satisfy it directly; the cast says the
    narrowing once instead of at each request test.
    """
    base: dict[str, Any] = {"headers": {}}
    base.update(extra)
    return cast(OnlineParamTypes, cast(object, base))


def _url(params: OnlineParamTypes) -> str:
    """The URL ``request()`` built. ``HTTPParams.url`` is optional, so every
    request test would otherwise have to repeat the narrowing."""
    return params.get("url") or ""


# A real result card: name + ticker in the <h3>, the update line, two badges.
CARD = (
    '<a href="/spolki/alibaba/" class="flex flex-col gap-3 flex-1 min-w-0 sm:gap-1.5">'
    '<div><img src="/media/alibaba.webp" alt="Alibaba logo"></div>'
    '<h3 class="font-bold text-highlighted truncate">Alibaba Group '
    '<span class="font-normal text-dimmed">(BABA)</span></h3>'
    '<p class="flex items-center gap-1.5 text-xs text-dimmed">'
    '<span class="iconify i-dna:calendar"></span> Aktualizacja: 25 cze 2026</p>'
    '<span data-slot="base" class="font-medium"><span data-slot="label" '
    'class="truncate leading-4">NYSE</span></span>'
    '<span data-slot="base" class="font-medium"><span data-slot="label" '
    'class="truncate leading-4">USD</span></span>'
    "</a>"
)

# A GPW card whose update line is absent — verified on the live site, so the
# parser must not assume the date is there.
CARD_NO_DATE = (
    '<a href="/spolki/kghm/" class="flex flex-col gap-3 flex-1 min-w-0 sm:gap-1.5">'
    '<h3 class="font-bold">KGHM <span class="font-normal">(KGH)</span></h3>'
    '<span data-slot="label" class="truncate leading-4">GPW</span>'
    '<span data-slot="label" class="truncate leading-4">PLN</span>'
    "</a>"
)

# What the site returns for a query that matches nothing.
EMPTY_PAGE = (
    '<div class="col-span-12 xl:col-span-9 flex flex-col gap-4">'
    '<span class="text-dimmed text-base xl:text-lg mb-0.5 shrink-0"> (0) </span>'
    '<input type="text" value="zzzqqqxxnosuchterm" placeholder="Szukaj spółki">'
    '<p class="text-lg text-dimmed">Nie znaleziono spółek dla podanych parametrów.</p>'
    "</div>"
)


def _resp(text, status_code=200):
    r = Mock()
    r.text = text
    r.status_code = status_code
    return r


class DnaRynkowEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_dnarynkow.yml"

    def setUp(self):
        super().setUp()
        self.engine = searx.engines.engines["dna rynkow"]

    # -- the query interface -------------------------------------------------

    def test_request_targets_the_stock_index_with_a_search_param(self):
        params = _params()
        self.engine.request("alibaba", params)
        self.assertIn("/spolki/", _url(params))
        self.assertIn("search=alibaba", _url(params))
        # The whole point: this is a parameter, not a route. Nothing named
        # /szukaj or /search exists on this site.
        self.assertNotIn("/szukaj", _url(params))

    def test_request_carries_the_page_number(self):
        params = _params()
        self.engine.request("alibaba", params)
        self.assertIn("page=1", _url(params))
        params = _params(pageno=3)
        self.engine.request("alibaba", params)
        self.assertIn("page=3", _url(params))

    def test_request_encodes_reserved_characters(self):
        params = _params(pageno=2)
        self.engine.request("AT&T", params)
        self.assertIn("search=AT%26T", _url(params))
        self.assertTrue(_url(params).endswith("&page=2"))

    def test_paging_is_enabled(self):
        self.assertTrue(self.engine.paging)

    def test_no_user_agent_is_set(self):
        """This site serves every UA equally, including none, so the engine
        sets none — unlike SII, which rejects a degenerate UA."""
        params = _params()
        self.engine.request("alibaba", params)
        self.assertEqual(params["headers"], {})

    def test_a_non_200_status_still_raises(self):
        for code in (403, 429, 500):
            with self.assertRaises(SearxEngineResponseException):
                self.engine.response(_resp("", status_code=code))

    # -- parsing -------------------------------------------------------------

    def test_a_card_yields_its_url_title_and_ticker(self):
        results = self.engine.response(_resp(CARD))
        self.assertEqual(len(results), 1)
        r = _first(results)
        self.assertEqual(r.url, "https://dnarynkow.pl/spolki/alibaba/")
        self.assertIn("Alibaba Group", r.title)
        self.assertIn("BABA", r.title, "the ticker lives in a nested span")

    def test_the_polish_update_date_is_parsed(self):
        results = self.engine.response(_resp(CARD))
        self.assertEqual(_first(results).publishedDate, datetime(2026, 6, 25))

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
            card = CARD.replace("25 cze 2026", f"25 {abbr} 2026")
            results = self.engine.response(_resp(card))
            # The whole date, not just .month: it says the same thing and leaves
            # nothing Optional to narrow.
            self.assertEqual(_first(results).publishedDate, datetime(2026, month, 25), f"month {abbr}")

    def test_a_missing_update_date_is_not_a_failure(self):
        results = self.engine.response(_resp(CARD_NO_DATE))
        self.assertEqual(len(results), 1)
        self.assertIsNone(_first(results).publishedDate)
        self.assertIn("KGHM", _first(results).title)

    def test_venue_and_currency_are_carried(self):
        results = self.engine.response(_resp(CARD))
        self.assertIn("NYSE", _first(results).content)
        self.assertIn("USD", _first(results).content)

    def test_an_empty_page_yields_nothing(self):
        self.assertEqual(len(self.engine.response(_resp(EMPTY_PAGE))), 0)

    def test_duplicate_cards_appear_once(self):
        self.assertEqual(len(self.engine.response(_resp(CARD + CARD))), 1)

    def test_two_cards_do_not_bleed_into_each_other(self):
        results = self.engine.response(_resp(CARD + CARD_NO_DATE))
        self.assertEqual(len(results), 2)
        rows = _rows(results)
        titles = " ".join(r.title for r in rows)
        self.assertIn("Alibaba", titles)
        self.assertIn("KGHM", titles)
        self.assertIsNotNone(rows[0].publishedDate)
        self.assertIsNone(rows[1].publishedDate)

    def test_the_category_is_finance(self):
        self.assertEqual(self.engine.categories, ["finance", "finance-poland"])
