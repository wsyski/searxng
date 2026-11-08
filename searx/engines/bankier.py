# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bankier (bankier.pl) — Polish financial portal, full-text news search

A plain server-rendered search page::

    https://www.bankier.pl/wyszukiwarka?qt=<terms>&page=<n>

One hit is an article row (``<article class="article hentry">``) with an
absolute title link, an ISO ``<time class="entry-date">`` and a teaser
paragraph. A query with no matches is **200** with
``Znaleziono: <strong>0</strong>`` and no article rows, so zero results needs
no special case. Paging is ``&page=2`` from the site's own pagination links.

.. attention::

   **The parameter is ``qt``, not ``q``.** Measured 2026-11-08:
   ``/wyszukiwarka?query=``, ``?kw=`` and ``/search/?query=`` each return the
   same 31,450-byte page — the search form with zero hits — for every term
   including a real one, so a wrong parameter reads as "engine healthy, found
   nothing". ``?qt=KGHM`` returns 78,442 bytes and rows. ``qt`` is full text,
   not ticker-only: ``KGHM`` finds 19,098 hits.

robots.txt (checked 2026-11-08): ``User-agent: *`` disallows only asset and
forum paths (``/content``, ``/e/``, …), none of them the search; GPTBot,
Bard, CCbot and Google-Extended are disallowed everywhere by name, which does
not cover SearXNG's UA. A burst of five searches answered 200 each.
"""

import re
from datetime import datetime
from urllib.parse import urlencode

from searx.exceptions import SearxEngineResponseException
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://www.bankier.pl",
    "official_api_documentation": None,
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["finance", "finance poland"]
paging = True

base_url = "https://www.bankier.pl"

# One row per <article>. The title anchor is the canonical article URL; the
# datetime attribute carries the offset, the first entry-content <p> the teaser.
_ITEM_RE = re.compile(
    r'<article class="article hentry".*?'
    r'<h2 class="entry-title">\s*<a href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<time class="entry-date" datetime="(?P<date>[^"]+)"[^>]*>.*?</time>.*?'
    r'<div class="entry-content">(?P<teaser>.*?)</div>',
    re.S,
)

_TEASER_RE = re.compile(r"<p>(.*?)</p>", re.S)


def request(query, params):
    params["url"] = f"{base_url}/wyszukiwarka?" + urlencode(
        {"qt": query, "page": params.get("pageno", 1)}
    )
    params["raise_for_httperror"] = False
    return params


def response(resp) -> EngineResults:
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"bankier: unexpected status {resp.status_code}")

    results = EngineResults()
    seen = set()
    for match in _ITEM_RE.finditer(resp.text):
        url = match.group("href")
        if not url.startswith("http"):
            url = f"{base_url}{url}"
        if url in seen:
            continue
        seen.add(url)

        title = _text(match.group("title"))
        if not title:
            continue
        teaser = _TEASER_RE.search(match.group("teaser"))
        results.add(
            results.types.LegacyResult(
                {
                    "url": url,
                    "title": title,
                    "content": _text(teaser.group(1)) if teaser else "",
                    "publishedDate": _published(match.group("date")),
                }
            )
        )

    return results


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(fragment)).strip()


def _published(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
