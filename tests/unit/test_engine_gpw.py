# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name,protected-access

"""Tests for the GPW (gpw.pl) ESPI/EBI company-reports engine.

Pinned behaviours, all measured on the live site 2026-11-08:

- the request is a POST to ``/ajaxindex.php`` with the site's own
  serialized form: raw ``application/x-www-form-urlencoded`` with repeated
  checkbox keys. curl_cffi's dict-array encoding of the same fields is
  answered a "Request Rejected" page, so the engine must send the exact
  ``content`` body itself.
- the engine ships a script ``User-Agent``: the WAF resets the connection
  for any UA containing "Mozilla".
- the empty state is a whitespace-only fragment = zero results; a
  non-empty fragment without rows is an error page and must raise.
- rows parse to absolute ``/komunikat?geru_id=...`` URLs with Polish
  ``%d-%m-%Y %H:%M:%S`` dates, and a report without a subject line falls
  back to the report-kind line in the title.
"""

import typing as t
from datetime import datetime
from unittest.mock import Mock

import searx.engines
import searx.engines.gpw as gpw_mod
from searx.exceptions import SearxEngineResponseException
from searx.result_types import LegacyResult
from searx.search.processors import OnlineParamTypes
from tests import SearxTestCase


def _params(**extra: t.Any) -> OnlineParamTypes:
    base: dict[str, t.Any] = {"headers": {}}
    base.update(extra)
    return t.cast(OnlineParamTypes, t.cast(object, base))


def _resp(text, status_code=200):
    r = Mock()
    r.text = text
    r.status_code = status_code
    return r


def _content(params: OnlineParamTypes) -> str:
    raw: object = params["content"]
    # the form body must travel as a str so curl_cffi sends it verbatim
    return raw.decode() if isinstance(raw, bytes) else str(raw)


# Real markup, trimmed from the ajaxindex fragment: dated span, company
# anchor, subject <p>. The second row is a periodic report: no subject.
ROWS = """\
<li style="padding: 15px 0;">
    <span class="date">03-11-2026 13:23:45 | Bieżący | ESPI | 40/2026</span>
    <strong class="name">
        <a href="komunikat?geru_id=499908&amp;title=Wykaz+akcjonariuszy">
            KGHM POLSKA MIEDŹ SPÓŁKA AKCYJNA (PLKGHM000017)
        </a>
    </strong>
    <span class="summary margin-left-30 pull-right"><small>Kurs</small>276,80</span>
    <p>
        Wykaz akcjonariuszy posiadających co najmniej 5% liczby głosów na Nadzwyczajnym Walnym Zgromadzeniu
    </p>
    <a href="komunikat?geru_id=499908&amp;title=Wykaz+akcjonariuszy">więcej &gt;</a>
</li>
<li style="padding: 15px 0;">
    <span class="date">06-11-2026 17:32:08 | Kwartalny | ESPI | /2026</span>
    <strong class="name">
        <a href="komunikat?geru_id=500177">
            ALTUS SPÓŁKA AKCYJNA (PLATTFI00018)
        </a>
    </strong>
</li>
"""

REJECTED = (
    '<html><head><title>Request Rejected</title></head>'
    '<body>The requested URL was rejected on this web site.</body></html>'
)


class GpwEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_gpw.yml"

    def setUp(self):
        super().setUp()
        self.engine = t.cast(t.Any, searx.engines.engines["gpw"])

    def test_request_is_a_post_of_the_exact_form_body(self):
        params = _params()
        self.engine.request("KGHM", params)
        self.assertEqual(params["method"], "POST")
        self.assertEqual(params["url"], "https://www.gpw.pl/ajaxindex.php")
        body = _content(params)
        self.assertIn("action=GPWEspiReportUnion", body)
        self.assertIn("start=ajaxSearch", body)
        # the site's repeated-keys encoding, not curl_cffi's array syntax
        self.assertIn("categoryRaports%5B%5D=EBI&categoryRaports%5B%5D=ESPI", body)
        self.assertIn("typeRaports%5B%5D=RB&typeRaports%5B%5D=P", body)
        self.assertIn("searchText=KGHM", body)
        self.assertEqual(params["headers"]["Content-Type"], "application/x-www-form-urlencoded")

    def test_request_carries_the_script_user_agent(self):
        params = _params()
        self.engine.request("KGHM", params)
        self.assertEqual(params["headers"]["User-Agent"], "SearXNG/1.0")

    def test_request_encodes_the_page_offset(self):
        p1, p3 = _params(), _params(pageno=3)
        self.engine.request("KGHM", p1)
        self.engine.request("KGHM", p3)
        self.assertIn("offset=0", _content(p1))
        self.assertIn("offset=30", _content(p3))

    def test_request_escapes_reserved_characters(self):
        params = _params()
        self.engine.request("AT&T & C#", params)
        body = _content(params)
        self.assertIn("searchText=AT%26T+%26+C%23", body)

    def test_paging_is_enabled(self):
        self.assertTrue(self.engine.paging)

    def test_the_category_is_finance_poland(self):
        self.assertEqual(self.engine.categories, ["finance", "finance poland"])

    def test_rows_parse_dates_subjects_and_absolute_urls(self):
        results = self.engine.response(_resp(ROWS))
        self.assertEqual(len(results), 2)
        first = t.cast(LegacyResult, list(results)[0])
        self.assertEqual(
            first["url"],
            "https://www.gpw.pl/komunikat?geru_id=499908&title=Wykaz+akcjonariuszy",
        )
        self.assertEqual(
            first["title"],
            "KGHM POLSKA MIEDŹ SPÓŁKA AKCYJNA (PLKGHM000017) — Wykaz akcjonariuszy "
            "posiadających co najmniej 5% liczby głosów na Nadzwyczajnym Walnym Zgromadzeniu",
        )
        self.assertEqual(first["publishedDate"], datetime(2026, 11, 3, 13, 23, 45))
        self.assertEqual(first["content"], "Bieżący | ESPI | 40/2026")

    def test_a_report_without_a_subject_is_titled_by_its_kind(self):
        second = t.cast(LegacyResult, list(self.engine.response(_resp(ROWS)))[1])
        self.assertEqual(second["title"], "ALTUS SPÓŁKA AKCYJNA (PLATTFI00018) — raport Kwartalny | ESPI | /2026")
        self.assertIsNone(second["publishedDate"] and second["publishedDate"].tzinfo)

    def test_the_whitespace_fragment_is_zero_results(self):
        self.assertEqual(len(self.engine.response(_resp("\r\n\r\n  \r\n"))), 0)

    def test_a_fragment_without_rows_is_an_error_not_zero(self):
        # the WAF's 200 + "Request Rejected" page must not read as "no hits"
        with self.assertRaises(SearxEngineResponseException):
            self.engine.response(_resp(REJECTED))

    def test_an_unexpected_status_is_a_response_exception(self):
        with self.assertRaises(SearxEngineResponseException):
            self.engine.response(_resp("<html>boom</html>", 500))

    def test_the_limit_is_the_sites_own(self):
        self.assertEqual(gpw_mod._LIMIT, 15)
