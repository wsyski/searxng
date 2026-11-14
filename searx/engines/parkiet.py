# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parkiet (parkiet.com) — Polish business daily (Bloomberg Polska), search

The visible page at::

    https://www.parkiet.com/szukaj/<terms>

is a client-side shell whose result container is **empty in the HTML**; the
rows are fetched from the same URL with ``?ajax=1`` appended, which answers
JSON ``{"isLoadMore": 0|1, "html": "<fragment>"}`` — server-rendered rows the
engine parses out of the fragment (the JS load-more does exactly this)::

    https://www.parkiet.com/szukaj/<terms>?ajax=1&page=<n>

.. attention::

   **Plain ``/szukaj?q=...`` is dead and ``?page=`` is ignored.** Measured
   2026-11-08: ``/szukaj?q=KGHM`` answers **301 to ``/``** (the site's own
   "Redirecting to /" stub — the old query form no longer exists), and the
   term must live in the *path*: ``/szukaj/KGHM`` works, with spaces
   percent-encoded (``/szukaj/CYFROWY%20POLSAT`` returns 10 rows). Inside the
   JSON fragment one row is a ``content--block``: title anchor to
   ``/<section>/art<id>-<slug>`` plus ``<h2 class="t--60">``, a
   ``.overline--comp`` date ``17:43 - 06.11.2026`` and a ``.teaser--lead``
   teaser. No matches is an empty fragment with ``isLoadMore: 0`` — zero
   results, not an error.

The bare page is served to any UA (the Incapsula-free host); a browser-like
UA is required — ``SearXNG/2026.01`` is fine on ``/szukaj/<term>``.
"""

import json
import re
from datetime import datetime
from urllib.parse import quote, urlencode

from searx.exceptions import SearxEngineResponseException
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://www.parkiet.com",
    "official_api_documentation": None,
    "use_official_api": False,
    "require_api_key": False,
    "results": "JSON (HTML fragment)",
}

categories = ["finance", "finance poland"]
paging = True

base_url = "https://www.parkiet.com"

# One row per content--block inside the JSON "html" fragment.
_ITEM_RE = re.compile(
    r'<div class="overline--comp[^"]*">(?P<date>[^<]+)</div>.*?'
    r'href="(?P<href>/[^"]*art\d+[^"]*)"[^>]*>\s*<h2[^>]*>(?P<title>.*?)</h2>.*?'
    r'<p class="teaser--lead[^"]*">(?P<teaser>.*?)</p>',
    re.S,
)

_DATE_FMT = "%H:%M - %d.%m.%Y"


def request(query, params):
    # The term is a path segment (spaces percent-encode); page 1 is the same
    # URL with page=1, which the site's load-more uses.
    params["url"] = f"{base_url}/szukaj/{quote(query.strip())}?" + urlencode(
        {"ajax": "1", "page": params.get("pageno", 1)}
    )
    params["raise_for_httperror"] = False
    return params


def response(resp) -> EngineResults:
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"parkiet: unexpected status {resp.status_code}")

    try:
        fragment = json.loads(resp.text)["html"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SearxEngineResponseException(f"parkiet: not the ajax JSON ({exc})") from exc

    results = EngineResults()
    seen = set()
    for match in _ITEM_RE.finditer(fragment):
        url = f"{base_url}{match.group('href')}"
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
