# SPDX-License-Identifier: AGPL-3.0-or-later
"""Biznesradar (biznesradar.pl) — Polish stock-data portal, per-company news

The news page of one company is server-rendered and carries an aggregated
press feed — external articles with title, teaser and source::

    https://www.biznesradar.pl/wiadomosci/<SLUG>          page 1
    https://www.biznesradar.pl/wiadomosci/<SLUG>,<n>      page n > 1

It is also a ticker lookup: ``/wiadomosci/PKN`` answers **301** to the
canonical ``/wiadomosci/ORLEN``, so a ticker query arrives at the company page
through the redirect the network layer follows. An unknown symbol answers
**404**, which this engine reports as zero results, not as a failure.

.. attention::

   **The slug is case-sensitive and pages live in the path.** Measured
   2026-11-08: ``/wiadomosci/ORLEN`` is 200 with 20 rows while
   ``/wiadomosci/orlen`` is 404, so ``request`` upper-cases the query and maps
   spaces to hyphens (``CYFROWY-POLSAT`` is a real slug; its ticker ``CPS``
   301s to it). ``?page=2`` is silently ignored — the bare page and
   ``?page=2`` return identical ``msg-`` ids — while the real page 2 is
   ``/wiadomosci/ORLEN,2``, the href of the site's own "następna" link.

No gate, no cookies: ``SearXNG/2026.01`` is served the full page, so the
engine sets no UA.
"""

import re
from datetime import datetime

from searx.exceptions import SearxEngineResponseException
from searx.network import get
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://www.biznesradar.pl",
    "official_api_documentation": None,
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["finance", "finance poland"]
paging = True

base_url = "https://www.biznesradar.pl"

# One row: the header anchor is the external article (absolute URL, rel
# nofollow), the teaser follows in record-body and the footer carries
# <span class="record-date">2026-11-05 17:56:13</span>.
_ITEM_RE = re.compile(
    r'<div id="msg-\d+" class="record record-type-[A-Z]+">.*?'
    r'<div class="record-header">\s*<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<div class="record-body">(?P<teaser>.*?)</div>.*?'
    r'<span class="record-date">(?P<date>[^<]+)</span>',
    re.S,
)

_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def request(query, params):
    # The slug is case-sensitive and hyphenated; the comma form is the site's
    # own pagination and works for every page, page 1 included.
    slug = re.sub(r"\s+", "-", query.strip().upper())
    pageno = params.get("pageno", 1)
    params["url"] = f"{base_url}/wiadomosci/{slug},{pageno}"
    # 404 is the unknown-symbol answer (verified: ZZQXV); every other non-200
    # is diagnosed in response().
    params["raise_for_httperror"] = False
    return params


def response(resp) -> EngineResults:
    if resp.status_code == 404:
        return EngineResults()
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"biznesradar: unexpected status {resp.status_code}")

    results = EngineResults()
    seen = set()
    for match in _ITEM_RE.finditer(resp.text):
        url = match.group("url")
        if url in seen:
            continue
        seen.add(url)

        title = _text(match.group("title"))
        if not title:
            continue
        results.add(
            results.types.LegacyResult(
                {
                    "url": url,
                    "title": title,
                    "content": _text(match.group("teaser")),
                    "publishedDate": _published(match.group("date")),
                }
            )
        )

    return results


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(fragment)).strip()


def _published(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), _DATE_FMT)
    except ValueError:
        return None
