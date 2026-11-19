# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name

"""Tests for the fork-local publishedDate in searx/engines/bing_news.py.

Bing gives an item's age only as display text in the market's language; the
labels below are ones the live engine returned on 2026-11-19 (en, en-GB, pl, sv,
de, nb, da, fr). A label that is not a date must give None, never a guess.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from lxml import html

from searx.engines import bing_news
from tests import SearxTestCase

NOW = datetime(2026, 11, 19, 12, 0)


class TestPublishedDate(SearxTestCase):

    def d(self, label, locale=""):
        return bing_news.published_date(label, locale, NOW)

    def test_relative_labels(self):
        cases = {
            "11 minutes ago": timedelta(minutes=11),
            "1 hour ago": timedelta(hours=1),
            "6 days ago": timedelta(days=6),
            "Vor 1 Stunde": timedelta(hours=1),
            "Vor 2 Tagen": timedelta(days=2),
            "Vor einem Tag": timedelta(days=1),
            "4 timmar sedan": timedelta(hours=4),
            "2 dagar sedan": timedelta(days=2),
            "10 timer siden": timedelta(hours=10),
            "for 1 dag siden": timedelta(days=1),
            "for 2 dage siden": timedelta(days=2),
            "Il y a 3 jours": timedelta(days=3),
            "2 godz. temu": timedelta(hours=2),
            "3 dni temu": timedelta(days=3),
            "5 minut temu": timedelta(minutes=5),
            "a month ago": timedelta(days=30),
        }
        for label, ago in cases.items():
            self.assertEqual(self.d(label), NOW - ago, label)

    def test_absolute_labels(self):
        self.assertEqual(self.d("29.10.2026"), datetime(2026, 10, 29))
        self.assertEqual(self.d("4.05.2026"), datetime(2026, 5, 4))
        self.assertEqual(self.d("2026-10-23"), datetime(2026, 10, 23))
        self.assertEqual(self.d("Nov 12, 2025"), datetime(2025, 11, 12))

    def test_slash_dates_follow_the_market(self):
        self.assertEqual(self.d("03/11/2026", "fr-FR"), datetime(2026, 11, 3))
        self.assertEqual(self.d("03/11/2026", "en-US"), datetime(2026, 3, 11))
        self.assertEqual(self.d("15/10/2026", "en-US"), datetime(2026, 10, 15))

    def test_yesterday_and_not_a_date(self):
        self.assertEqual(self.d("wczoraj"), NOW - timedelta(days=1))
        for label in ("", "Bankier.pl", "31.02.2026", "the 3 musketeers"):
            self.assertIsNone(self.d(label), label)

    def test_response_sets_published_date_and_keeps_metadata(self):
        page = (
            '<div class="newsitem"><a class="title" href="https://x/1" data-author="Bankier.pl">T</a>'
            '<div class="snippet">S</div><div class="source"><span aria-label="29.10.2026"></span></div></div>'
            '<div class="newsitem"><a class="title" href="https://x/2" data-author="Src">U</a>'
            '<div class="snippet">S</div><div class="source"><span aria-label="Bankier.pl"></span></div></div>'
        )
        resp = SimpleNamespace(html=lambda: html.fromstring(page), search_params={"searxng_locale": "pl"})
        first, second = bing_news.response(resp)  # pylint: disable=unbalanced-tuple-unpacking
        self.assertEqual(first["publishedDate"], datetime(2026, 10, 29))
        self.assertEqual(first["metadata"], "29.10.2026 | Bankier.pl")
        self.assertNotIn("publishedDate", second)
