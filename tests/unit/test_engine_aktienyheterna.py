# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name
"""Tests for the Aktienyheterna (aktienyheterna.se) engine.

Every assertion pins something measured on the live API on 2026-10-30 that a
future edit can break without failing anything else. The one that matters most:

- WordPress ``search`` matches a **substring of the body**, so ``?search=granges``
  returns two Spendrups sustainability posts that name **Grängesberg**, a town,
  and nothing about Gränges. Without the whole-word filter the portfolio's
  "has anyone written about this holding" question is answered "yes, twice".
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
    """The article rows, with the ``engine_data`` entries filtered out.

    ``engine_data`` travels as entries in the same result list (``searx/results.py``,
    the ``engine_data`` branch; ``deviantart.py`` is the upstream precedent), so a
    row count has to say which it means.
    """
    return [r for r in results if "engine_data" not in r]


def _engine_data(results):
    """The ``{key: value}`` pairs the engine published."""
    return {r["key"]: r["engine_data"] for r in results if "engine_data" in r}


def _first(results):
    """The first row, narrowed to what this engine builds.

    ``EngineResults`` yields the base ``Result``; ``content`` and
    ``publishedDate`` belong to ``LegacyResult``.
    """
    return cast(LegacyResult, _rows(results)[0])


def _params(**extra: Any) -> OnlineParamTypes:
    base: dict[str, Any] = {"headers": {}}
    base.update(extra)
    return cast(OnlineParamTypes, cast(object, base))


def _url(params: OnlineParamTypes) -> str:
    return params.get("url") or ""


def _post(
    title, body="", excerpt="", link="https://www.aktienyheterna.se/blog/x", date="2026-10-22T07:30:00"
) -> dict[str, Any]:
    return {
        "id": 1,
        "date_gmt": date,
        "link": link,
        "title": {"rendered": title},
        "excerpt": {"rendered": f"<p>{excerpt}</p>"},
        "content": {"rendered": f"<article><p>{body}</p></article>"},
    }


# The real 2026-10-30 answer to ?search=granges: two posts, neither about
# Gränges. "granges" is a substring of "Grängesberg", the Dalarna town.
GRANGESBERG_POSTS = [
    _post(
        "Spendrups hållbarhetsrapport 2024: 94% utsläppsminskning",
        body="Biogas från bryggrester täcker nu 100 procent av värmebehovet i Grängesberg.",
        excerpt="Upptäck Spendrups framsteg i hållbarhetsarbetet.",
        link="https://www.aktienyheterna.se/blog/spendrups-hallbarhetsrapport-2024",
    ),
    _post(
        "Spendrups hållbarhetsframsteg 2024",
        body="Spendrups grundades 1897 i Grängesberg och drivs i fjärde generationen.",
        link="https://www.aktienyheterna.se/blog/spendrups-hallbarhetsframsteg-2024",
    ),
]


def _resp(payload, status_code=200, query="granges"):
    r = Mock()
    r.status_code = status_code
    r.json = Mock(return_value=payload)
    # `query` is what the relevance filter reads; the online processor sets it
    # (searx/search/processors/online.py), as open_meteo.py and dictzone.py do.
    r.search_params = {"query": query}
    return r


class _AktienyheternaTestCase(SearxTestCase):

    TEST_SETTINGS = "test_aktienyheterna.yml"

    def setUp(self):
        super().setUp()
        self.engine = searx.engines.engines["aktienyheterna"]


class AktienyheternaRequestTests(_AktienyheternaTestCase):

    def test_request_uses_the_wordpress_search_parameter(self):
        params = _params()
        self.engine.request("granges", params)
        self.assertIn("/wp-json/wp/v2/posts?", _url(params))
        self.assertIn("search=granges", _url(params))

    def test_request_asks_only_for_the_fields_response_reads(self):
        """Without _fields, content.rendered arrives wrapped in a <style> blob."""
        params = _params()
        self.engine.request("granges", params)
        self.assertIn("_fields=", _url(params))
        for field in ("title", "excerpt", "content", "link", "date_gmt"):
            self.assertIn(field, _url(params))

    def test_request_asks_for_the_body_because_the_filter_reads_it(self):
        """A body-only mention is a legitimate hit (the ksiazak property), so the
        haystack cannot be narrowed to the title - which is why `content` is in
        _fields even though it never reaches a result row."""
        params = _params()
        self.engine.request("granges", params)
        self.assertIn("content", _url(params))

    def test_request_carries_the_page_number(self):
        params = _params(pageno=3)
        self.engine.request("granges", params)
        self.assertIn("page=3", _url(params))

    def test_request_encodes_reserved_characters(self):
        """A raw f-string turns `AT&T` into search=AT plus a stray `T` parameter."""
        params = _params()
        self.engine.request("AT&T C#", params)
        self.assertIn("search=AT%26T+C%23", _url(params))

    def test_request_identifies_itself(self):
        params = _params()
        self.engine.request("granges", params)
        self.assertEqual(params["headers"]["User-Agent"], "SearXNG/1.0")

    def test_the_engine_is_in_the_swedish_finance_categories(self):
        self.assertEqual(self.engine.categories, ["finance", "finance-sweden"])

    def test_paging_is_enabled(self):
        """WordPress pages, and answers 400 past the end - see below."""
        self.assertTrue(self.engine.paging)


class AktienyheternaStatusTests(_AktienyheternaTestCase):

    def test_a_400_is_an_empty_result_not_a_failure(self):
        """WordPress answers 400 for a page past the end, which is how a user
        paging to the last page learns to stop."""
        results = self.engine.response(_resp([], status_code=400))
        self.assertEqual(len(_rows(results)), 0)

    def test_a_400_still_publishes_its_counts(self):
        """The whole point of engine_data: "ran and found nothing" must be
        distinguishable from "did not run", and a 400 is the former."""
        results = self.engine.response(_resp([], status_code=400))
        self.assertEqual(_engine_data(results), {"dropped_rows": "0", "site_rows": "0"})

    def test_any_other_error_status_still_raises(self):
        for code in (403, 500, 503):
            with self.assertRaises(SearxEngineResponseException):
                self.engine.response(_resp([], status_code=code))


class AktienyheternaFilterTests(_AktienyheternaTestCase):

    def test_grangesberg_is_not_granges(self):
        """THE trap, measured 2026-10-30. Both live rows for ?search=granges are
        Spendrups posts naming the town Grängesberg; neither is about Gränges.
        Two confident rows about a brewery are worse than none."""
        results = self.engine.response(_resp(GRANGESBERG_POSTS, query="granges"))
        self.assertEqual(len(_rows(results)), 0)

    def test_the_drop_is_published_rather_than_only_logged(self):
        """`general.debug` is false on the deployed instance and the consumer
        reads the JSON response, not this instance's log."""
        results = self.engine.response(_resp(GRANGESBERG_POSTS, query="granges"))
        self.assertEqual(_engine_data(results), {"dropped_rows": "2", "site_rows": "2"})

    def test_a_title_hit_is_kept(self):
        payload = [_post("Swedbank rapporterar som väntat", excerpt="Räntenettot höll.")]
        results = self.engine.response(_resp(payload, query="swedbank"))
        self.assertEqual(len(_rows(results)), 1)
        self.assertEqual(_engine_data(results), {"dropped_rows": "0", "site_rows": "1"})

    def test_a_body_only_hit_is_kept(self):
        """The ksiazak property: a note about one company can discuss another
        inside it, and that is a real answer to "who has written about X"."""
        payload = [_post("Tre verkstadsbolag att följa", body="Bland dem finns Gränges.")]
        results = self.engine.response(_resp(payload, query="granges"))
        self.assertEqual(len(_rows(results)), 1)

    def test_the_fold_matches_swedish_diacritics(self):
        """ä decomposes under NFKD, so "granges" must match "Gränges"."""
        payload = [_post("Gränges höjer utsikterna")]
        self.assertEqual(len(_rows(self.engine.response(_resp(payload, query="granges")))), 1)

    def test_the_fold_matches_letters_nfkd_leaves_alone(self):
        """ø and æ are letters, not combining marks - NFKD does not touch them,
        so without the translation table they never fold to o/ae."""
        payload = [_post("Børsen om Dæmpet efterspørgsel")]
        self.assertEqual(len(_rows(self.engine.response(_resp(payload, query="borsen")))), 1)

    def test_every_term_must_hit_not_just_one(self):
        payload = [_post("Swedbank rapporterar", body="Inget om verkstad.")]
        results = self.engine.response(_resp(payload, query="swedbank granges"))
        self.assertEqual(len(_rows(results)), 0)

    def test_a_hyphenated_ticker_is_not_matched_against_a_suffix(self):
        """Lookarounds rather than \\b: the term itself ends in a non-word
        character, where \\b anchors on the wrong side and any suffix passes."""
        payload = [_post("Ericsson B-aktien faller")]
        self.assertEqual(len(_rows(self.engine.response(_resp(payload, query="eric-b")))), 0)


class AktienyheternaParsingTests(_AktienyheternaTestCase):

    def test_the_excerpt_is_the_content_not_the_body(self):
        """A 15 kB article in a search row is unreadable; the excerpt is the
        author's own summary. The body is in the haystack, not in the result."""
        payload = [_post("Telia", body="x" * 2000, excerpt="Utdelningen behålls.")]
        row = _first(self.engine.response(_resp(payload, query="telia")))
        self.assertEqual(row.content, "Utdelningen behålls.")
        self.assertNotIn("xxxx", row.content)

    def test_the_date_is_parsed(self):
        payload = [_post("Telia", date="2026-10-22T07:30:00")]
        row = _first(self.engine.response(_resp(payload, query="telia")))
        self.assertEqual(row.publishedDate, datetime(2026, 10, 22, 7, 30))

    def test_an_unparseable_date_is_dropped_not_raised(self):
        payload = [_post("Telia", date="not-a-date")]
        row = _first(self.engine.response(_resp(payload, query="telia")))
        self.assertIsNone(row.publishedDate)

    def test_a_post_without_a_title_or_link_is_skipped(self):
        # link=None is what WordPress sends for an unpublished post; _post's
        # signature is typed, so the absence is built rather than passed.
        no_link = _post("Telia")
        no_link["link"] = None
        payload = [_post(""), no_link]
        results = self.engine.response(_resp(payload, query="telia"))
        self.assertEqual(len(_rows(results)), 0)
        # Skipped for being unusable is not the relevance filter's doing, so it
        # is not counted as a drop - site_rows would otherwise claim the site
        # returned rows this engine judged.
        self.assertEqual(_engine_data(results), {"dropped_rows": "0", "site_rows": "0"})

    def test_a_repeated_link_appears_once(self):
        payload = [_post("Telia", link="https://x/a"), _post("Telia igen", link="https://x/a")]
        self.assertEqual(len(_rows(self.engine.response(_resp(payload, query="telia")))), 1)

    def test_html_in_the_title_is_text_in_the_row(self):
        payload = [_post("Telia &amp; Co <em>höjer</em>")]
        row = _first(self.engine.response(_resp(payload, query="telia")))
        self.assertNotIn("<em>", row.title)
        self.assertIn("&", row.title)
