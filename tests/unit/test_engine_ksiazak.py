# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name

"""Tests for the Książak (konradksiazak.pl) engine.

The archive is six posts about six companies. That is the point, not a defect:
the engine answers "has this office written about a name I hold?", where a hit
is the signal and empty is normal. So the tests lean on the two behaviours that
are easy to get wrong and invisible when they are:

- WordPress `search` matches title AND body, so a hit does not mean the
  company is in the title. "orlen" returns the Atrem note. Asserting on that
  would be asserting something false about the source.
- WordPress answers 400 when you page past the end. That is how a user learns
  to stop, not an engine failure, and swallowing it as "no results" would hide
  a genuine break.
"""

from datetime import datetime
from unittest.mock import Mock

import searx.engines
from searx.exceptions import SearxEngineResponseException
from tests import SearxTestCase

# Real response shape, trimmed. excerpt is HTML, title is HTML.
POST = {
    "link": "https://konradksiazak.pl/noctiluca-najlepsza-spolka-deep-tech-na-gieldzie/",
    "date": "2026-01-07T14:17:19",
    "title": {"rendered": "Noctiluca: Najlepsza sp&#243;&#322;ka deep-tech na GPW?"},
    "excerpt": {"rendered": "<p>Sp&oacute;ka Noctiluca, toru&#324;ski pionier w obszarze deep-tech.</p>\n"},
}


def _resp(payload, status_code=200):
    r = Mock()
    r.json.return_value = payload
    r.status_code = status_code
    return r


class KsiazakEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_ksiazak.yml"

    def setUp(self):
        super().setUp()
        self.engine = searx.engines.engines["ksiazak"]

    # -- the request ---------------------------------------------------------

    def test_request_uses_the_wordpress_rest_api(self):
        params = {}
        self.engine.request("noctiluca", params)
        self.assertIn("/wp-json/wp/v2/posts", params["url"])
        self.assertIn("search=noctiluca", params["url"])

    def test_request_sends_no_user_agent(self):
        """The API answers every client identically; verified with none at all."""
        params = {"headers": {}}
        self.engine.request("noctiluca", params)
        self.assertEqual(params["headers"], {})

    def test_request_passes_the_page_number(self):
        params = {}
        self.engine.request("orlen", params)
        self.assertIn("page=1", params["url"])
        params = {"pageno": 2}
        self.engine.request("orlen", params)
        self.assertIn("page=2", params["url"])

    def test_paging_is_enabled(self):
        self.assertTrue(self.engine.paging)

    def test_it_declares_an_official_api(self):
        self.assertTrue(self.engine.about.use_official_api)

    # -- status handling -----------------------------------------------------

    def test_paging_past_the_end_is_empty_not_an_error(self):
        """WordPress answers 400 for page > total; that is the end of the list."""
        results = self.engine.response(_resp({"code": "rest_post_invalid_page_number"}, 400))
        self.assertEqual(len(results), 0)

    def test_other_error_statuses_still_raise(self):
        for code in (403, 429, 500):
            with self.assertRaises(SearxEngineResponseException):
                self.engine.response(_resp([], status_code=code))

    # -- parsing -------------------------------------------------------------

    def test_a_post_yields_its_link_title_and_excerpt(self):
        results = self.engine.response(_resp([POST]))
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.url, POST["link"])
        self.assertIn("Noctiluca", r.title)
        self.assertIn("deep-tech", r.content)

    def test_html_entities_are_decoded(self):
        """Polish diacritics arrive as entities; a raw &#322; is unreadable."""
        results = self.engine.response(_resp([POST]))
        self.assertNotIn("&#", results[0].title)
        self.assertIn("spółka", results[0].title)
        self.assertNotIn("&oacute;", results[0].content)

    def test_html_tags_are_stripped(self):
        results = self.engine.response(_resp([POST]))
        self.assertNotIn("<p>", results[0].content)

    def test_the_date_is_parsed(self):
        results = self.engine.response(_resp([POST]))
        self.assertEqual(results[0].publishedDate, datetime(2026, 1, 7, 14, 17, 19))

    def test_the_body_is_not_used_as_the_summary(self):
        """A 15 kB article in a search result is unreadable; the excerpt is
        the office's own summary of its own thesis."""
        post = dict(POST, content={"rendered": "<p>" + ("x" * 5000) + "</p>"})
        results = self.engine.response(_resp([post]))
        self.assertLess(len(results[0].content), 1000)

    def test_a_post_without_a_link_is_skipped(self):
        results = self.engine.response(_resp([dict(POST, link="")]))
        self.assertEqual(len(results), 0)

    def test_an_empty_result_set_is_empty(self):
        self.assertEqual(len(self.engine.response(_resp([]))), 0)

    def test_a_body_only_hit_is_still_returned(self):
        """WordPress searches content too: "orlen" finds the Atrem note.

        This looks wrong next to the result title and is not - it is the source
        behaving correctly, and the plan must not assume a hit implies the
        company is in the title.
        """
        post = dict(POST, title={"rendered": "Atrem: 220% w g&#243;r&#281;"})
        results = self.engine.response(_resp([post]))
        self.assertEqual(len(results), 1)
        self.assertIn("Atrem", results[0].title)
        self.assertNotIn("Orlen", results[0].title)

    def test_the_category_is_news(self):
        self.assertEqual(self.engine.categories, ["general"])
