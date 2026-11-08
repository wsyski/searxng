# SPDX-License-Identifier: AGPL-3.0-or-later
"""GPW (gpw.pl) — Warsaw Stock Exchange, company reports ESPI/EBI

The exchange's bivalent channel: every listed company's current (bieżący)
and periodic (periodic) reports (ESPI) and disclosures (EBI). A query is
a company — name, ticker or ISIN — and the rows are that company's reports,
newest first::

    POST https://www.gpw.pl/ajaxindex.php

The visible /komunikaty page server-renders the first 15 rows, but
searching and "Pokaż więcej" both POST the filter form's fields to
``ajaxindex.php``, which answers a bare HTML fragment of ``<li>`` rows
(the site's own JS appends it). This engine uses that fragment endpoint
directly; the empty state is a whitespace-only fragment, and paging is
``offset += limit``.

.. attention::

   **The WAF resets browser User-Agents and serves script ones.** Measured
   2026-11-08: any UA containing "Mozilla" — Chrome, Firefox, even the bare
   string "Mozilla/5.0" — is answered a connection reset (curl error 56),
   on HTTP/1.1 and HTTP/2 alike, while ``curl/8.5.0``, ``Wget/1.21`` and
   ``python-requests/2.32.3`` get the full page. It is the UA string, not
   the TLS fingerprint: a chrome-impersonated session passes as soon as its
   UA header is overridden. So the engine ships an honest script UA, like
   :ref:`sii engine <sii engine>` ships its own.

The site is served to plain clients with no gate.

.. attention::

   **The WAF judges the POST body too.** The form's checkbox fields repeat
   (``categoryRaports[]=EBI&categoryRaports[]=ESPI``); sent as
   ``application/x-www-form-urlencoded`` with repeated keys the WAF passes,
   but curl_cffi's own array encoding of list-valued dict fields is answered
   200 + a 5,039-byte "Request Rejected" page. Omitting the checkboxes
   entirely is *not* "all types" — it is an empty fragment. So the engine
   posts the exact serialized body itself (``content``, not ``data``).
"""

import typing as t
from datetime import datetime
from urllib.parse import urljoin, urlencode

from lxml import html as lx_html

from searx.exceptions import SearxEngineResponseException
from searx.result_types import EngineResults

about = {
    "website": "https://www.gpw.pl",
    "official_api_documentation": "https://www.gpw.pl/komunikaty",
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["finance", "finance poland"]
paging = True

base_url = "https://www.gpw.pl"

# The site's own form sends exactly these; the checkboxes are the two
# report channels and the five periodic-report kinds, all on.
_FORM = {
    "action": "GPWEspiReportUnion",
    "page": "komunikaty",
    "start": "ajaxSearch",
    "format": "html",
    "lang": "PL",
    "letter": "",
    "date": "",
    "categoryRaports[]": ["EBI", "ESPI"],
    "typeRaports[]": ["RB", "P", "Q", "O", "R"],
}
_LIMIT = 15

headers = {"User-Agent": "SearXNG/1.0"}

_DATE_FMT = "%d-%m-%Y %H:%M:%S"


def request(query, params):
    params["method"] = "POST"
    params["url"] = f"{base_url}/ajaxindex.php"
    data: dict[str, t.Any] = dict(_FORM)
    data["limit"] = str(_LIMIT)
    data["offset"] = str((max(params.get("pageno", 1) - 1, 0)) * _LIMIT)
    data["searchText"] = query
    # Raw urlencoded body, not the curl_cffi dict: curl_cffi's array
    # encoding of the list fields trips the WAF ("Request Rejected"),
    # while the site's own repeated-keys form encoding passes.
    params["content"] = urlencode(data, doseq=True)
    params["headers"].update(headers)
    params["headers"]["Content-Type"] = "application/x-www-form-urlencoded"
    return params


def response(resp) -> EngineResults:
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"gpw: unexpected status {resp.status_code}")

    results = EngineResults()

    # The no-match answer is a whitespace-only fragment (measured: 11 bytes
    # of newlines). Anything else that carries no row must be an error page,
    # not a silently empty result page.
    if not resp.text.strip():
        return results
    tree = lx_html.fromstring(resp.text)
    rows = tree.xpath("//li[.//span[@class='date']]")
    if not rows:
        raise SearxEngineResponseException(f"gpw: fragment without rows ({resp.text[:60]!r})")

    for row in rows:
        anchor = row.xpath(".//strong[@class='name']//a")
        date_span = row.xpath(".//span[@class='date']/text()")
        if not anchor or not date_span:
            continue
        href = anchor[0].get("href") or ""
        company = " ".join(anchor[0].text_content().split())
        meta = " ".join(date_span[0].split())
        date_part, _, kind = meta.partition(" | ")
        summaries = row.xpath(".//p/text()")
        subject = " ".join(" ".join(summaries).split())
        title = f"{company} — {subject}" if subject else f"{company} — raport {kind}"

        published = None
        try:
            published = datetime.strptime(date_part.strip(), _DATE_FMT)
        except ValueError:
            pass

        results.add(
            results.types.LegacyResult(
                {
                    "url": urljoin(f"{base_url}/komunikaty", href),
                    "title": title,
                    "content": kind,
                    "publishedDate": published,
                }
            )
        )

    return results
