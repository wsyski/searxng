# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name
"""Tests for the Placera (placera.se) engine.

Every assertion pins something measured on the live site on 2026-10-30:

- the path is ``/search``, not ``/sok`` (which 404s) and not ``/api/search``
  (which answers 200 with an empty object for every parameter name).
- the site ranks near-misses into the page: ``granges`` returns press releases
  about *grants* and board *changes*, and the nonsense query ``zzqxvv`` returns
  one row. Without the whole-word filter the Avanza books get those as hits.
- the date comes from the **slug**, because the rendered date has no year and
  the archive goes back to 2006.
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
    """The article rows, with the ``engine_data`` entries filtered out."""
    return [r for r in results if "engine_data" not in r]


def _engine_data(results):
    """The ``{key: value}`` pairs the engine published."""
    return {r["key"]: r["engine_data"] for r in results if "engine_data" in r}


def _first(results):
    """The first row, narrowed to what this engine builds."""
    return cast(LegacyResult, _rows(results)[0])


def _params(**extra: Any) -> OnlineParamTypes:
    base: dict[str, Any] = {"headers": {}}
    base.update(extra)
    return cast(OnlineParamTypes, cast(object, base))


def _url(params: OnlineParamTypes) -> str:
    return params.get("url") or ""


def _row(path, title):
    """One result row as the page renders it.

    The Tailwind class salad around it is deliberately omitted: the engine keys
    on `class="group" tabindex="-1"` wrapping an <h3>, which is the part that is
    not a style decision.
    """
    return f'<a class="group" tabindex="-1" href="{path}"><h3 class="font-sans text-xl font-bold">{title}</h3></a>'


# What a real /search?q=granges page carries: the hits, then the near-misses the
# site ranks in after them.
GRANGES_PAGE = "".join(
    [
        _row("/pressmeddelanden/granges-granges-valberedning-har-utsetts-20260930", "Gränges valberedning har utsetts"),
        _row(
            "/pressmeddelanden/granges-granges-nomination-committee-appointed-20260930",
            "Gränges&rsquo; Nomination Committee appointed",
        ),
        # Ranked in on "grants" and "changes", not on the query.
        _row(
            "/pressmeddelanden/ideaya-biosciences-announces-inducement-grants-20261030",
            "IDEAYA Biosciences Announces Inducement Grants",
        ),
        _row("/pressmeddelanden/bonava-changes-to-bonava-s-nomination-committee-20261028", "Changes to Bonava's"),
    ]
)

# Navigation furniture that shares the page but is not a row: the category chips
# and the breadcrumb, neither of which is an `a class="group"` wrapping an h3.
FURNITURE = (
    '<a href="/search?q=granges"><p class="font-sans">Alla</p></a>'
    '<a href="/search?q=granges&amp;category=analys"><p>Aktieanalys</p></a>'
    '<nav aria-label="breadcrumb"><a href="/kategorier/pressmeddelande">pressmeddelande</a></nav>'
)


def _resp(text, status_code=200, query="granges"):
    r = Mock()
    r.text = text
    r.status_code = status_code
    r.search_params = {"query": query}
    return r


class _PlaceraTestCase(SearxTestCase):

    TEST_SETTINGS = "test_placera.yml"

    def setUp(self):
        super().setUp()
        self.engine = searx.engines.engines["placera"]


class PlaceraRequestTests(_PlaceraTestCase):

    def test_request_uses_the_search_path_not_sok(self):
        """/sok?q=, /sok/<q> and /soek?q= all 404 with a ~35 kB app shell."""
        params = _params()
        self.engine.request("granges", params)
        self.assertIn("/search?", _url(params))
        self.assertNotIn("/sok", _url(params))

    def test_request_uses_the_q_parameter(self):
        params = _params()
        self.engine.request("granges", params)
        self.assertIn("q=granges", _url(params))

    def test_request_encodes_reserved_characters(self):
        """A raw f-string turns `AT&T` into q=AT plus a stray `T` parameter."""
        params = _params()
        self.engine.request("AT&T C#", params)
        self.assertIn("q=AT%26T+C%23", _url(params))

    def test_request_identifies_itself(self):
        """SearXNG/1.0 matches no named robots.txt group, so it falls under
        `User-agent: * / Allow: /` - which is the robots verdict this engine
        rests on."""
        params = _params()
        self.engine.request("granges", params)
        self.assertEqual(params["headers"]["User-Agent"], "SearXNG/1.0")

    def test_paging_is_disabled(self):
        """&page=2, &p=2 and &offset=100 each return the same 100-row page, so
        offering paging would be offering a no-op."""
        self.assertFalse(self.engine.paging)

    def test_the_engine_is_in_the_swedish_finance_categories(self):
        self.assertEqual(self.engine.categories, ["finance", "finance-sweden"])


class PlaceraStatusTests(_PlaceraTestCase):

    def test_an_error_status_raises(self):
        for code in (404, 500, 503):
            with self.assertRaises(SearxEngineResponseException):
                self.engine.response(_resp("", status_code=code))

    def test_a_page_with_no_rows_still_publishes_its_counts(self):
        """A row-less page is still an engine that ran, not one that did not."""
        results = self.engine.response(_resp(FURNITURE))
        self.assertEqual(len(_rows(results)), 0)
        self.assertEqual(_engine_data(results), {"dropped_rows": "0", "site_rows": "0"})


class PlaceraFilterTests(_PlaceraTestCase):

    def test_the_sites_near_misses_are_dropped(self):
        """Measured 2026-10-30: the granges page carries press releases about
        *grants* and board *changes*. The site returns a ranked list that trails
        off, not the term's hits."""
        results = self.engine.response(_resp(GRANGES_PAGE, query="granges"))
        self.assertEqual(len(_rows(results)), 2)
        self.assertEqual(_engine_data(results), {"dropped_rows": "2", "site_rows": "4"})

    def test_a_nonsense_query_keeps_nothing(self):
        """zzqxvv returned one row live - a ROKiT Drinks press release."""
        page = _row("/pressmeddelanden/rok-stars-plc-rok-drinks-re-brands-as-rokit-drinks-20190101", "ROK Drinks")
        results = self.engine.response(_resp(page, query="zzqxvv"))
        self.assertEqual(len(_rows(results)), 0)
        self.assertEqual(_engine_data(results), {"dropped_rows": "1", "site_rows": "1"})

    def test_a_typographic_apostrophe_still_matches_through_the_slug(self):
        """The title renders Gränges&rsquo;, so the slug is in the haystack."""
        results = self.engine.response(_resp(GRANGES_PAGE, query="granges"))
        self.assertTrue(any("nomination-committee" in r["url"] for r in _rows(results)))

    def test_every_term_must_hit_not_just_one(self):
        page = _row("/nyheter/swedbank-rapporterar-som-vantat-2026-10-22", "Swedbank rapporterar som väntat")
        self.assertEqual(len(_rows(self.engine.response(_resp(page, query="swedbank granges")))), 0)

    def test_the_fold_matches_swedish_diacritics(self):
        page = _row("/nyheter/x-2026-10-22", "Gränges höjer utsikterna")
        self.assertEqual(len(_rows(self.engine.response(_resp(page, query="granges")))), 1)

    def test_a_hyphenated_ticker_is_not_matched_against_a_suffix(self):
        """Lookarounds rather than \\b, which anchors on the wrong side when the
        term itself ends in a non-word character."""
        page = _row("/nyheter/ericsson-b-aktien-faller-2026-10-22", "Ericsson B-aktien faller")
        self.assertEqual(len(_rows(self.engine.response(_resp(page, query="eric-b")))), 0)

    def test_a_repeated_row_is_counted_once(self):
        """The live swedbank page carried one headline twice; a single article
        rejected twice would put a number in engine_data the page cannot support."""
        page = _row("/nyheter/swedbank-rapporterar-som-vantat-2026-10-22", "Swedbank rapporterar som väntat") * 2
        results = self.engine.response(_resp(page, query="swedbank"))
        self.assertEqual(len(_rows(results)), 1)
        self.assertEqual(_engine_data(results), {"dropped_rows": "0", "site_rows": "1"})


class PlaceraParsingTests(_PlaceraTestCase):

    def test_navigation_furniture_is_not_a_result(self):
        self.assertEqual(len(_rows(self.engine.response(_resp(FURNITURE)))), 0)

    def test_the_url_is_absolute(self):
        page = _row("/nyheter/granges-pa-topp-2015-02-04", "Gränges på topp")
        self.assertEqual(
            _first(self.engine.response(_resp(page))).url,
            "https://www.placera.se/nyheter/granges-pa-topp-2015-02-04",
        )

    def test_an_editorial_slug_date_is_parsed(self):
        page = _row("/nyheter/granges-pa-topp-2015-02-04", "Gränges på topp")
        self.assertEqual(_first(self.engine.response(_resp(page))).publishedDate, datetime(2015, 2, 4))

    def test_a_wire_slug_date_is_parsed(self):
        """The press-release wire writes it unseparated."""
        page = _row("/pressmeddelanden/granges-valberedning-20260930", "Gränges valberedning")
        self.assertEqual(_first(self.engine.response(_resp(page))).publishedDate, datetime(2026, 9, 30))

    def test_a_slug_without_a_date_yields_no_date_rather_than_raising(self):
        page = _row("/analys/svartolkat-granges", "Svårtolkat Gränges")
        self.assertIsNone(_first(self.engine.response(_resp(page))).publishedDate)

    def test_an_impossible_slug_date_is_dropped_not_raised(self):
        page = _row("/pressmeddelanden/granges-valberedning-20261340", "Gränges valberedning")
        results = self.engine.response(_resp(page))
        self.assertEqual(len(_rows(results)), 1)
        self.assertIsNone(_first(results).publishedDate)

    def test_html_entities_in_the_title_become_text(self):
        page = _row("/nyheter/granges-2026-10-22", "Gränges &amp; Co <em>höjer</em>")
        row = _first(self.engine.response(_resp(page)))
        self.assertNotIn("<em>", row.title)
        self.assertIn("&", row.title)
