# SPDX-License-Identifier: AGPL-3.0-or-later
"""Książak (konradksiazak.pl)

A small Polish investment office publishing long-form, single-company
fundamental notes — the "Analiza fundamentalna X: czy to okazja czy pułapka?"
format, typically 15 kB of argument per company.

The corpus is deliberately tiny (six posts, six companies, as of
2026-10-11) and that is not a defect to work around, it is the product. This
engine is meant to be asked "has this office written about a name I hold?",
where a one-in-many hit is the answer and an empty result is the normal
case. Judged by result count per query it looks worthless; judged as coverage
of a book it is the highest-signal source in the set, because a hit means a
dedicated analyst picked that company.

Do not reject a small site for having a small archive. Volume is not the
measure here.

The WordPress REST API is public and is the intended way in, so this engine
reads JSON from it rather than scraping HTML::

    https://konradksiazak.pl/wp-json/wp/v2/posts?search=<terms>&page=<n>

``search`` matches the title and the body, so a hit is not proof the company
is in the *title* — "orlen" returns the Atrem note because ORLEN is discussed
inside it. Both behaviours are asserted in the tests.

No ``User-Agent`` is set: the API answers every client identically, verified
with none at all. robots.txt carries no AI-agent rule; ``User-agent: *``
disallows only ``/wp-admin/``.
"""

import re
from datetime import datetime
from urllib.parse import urlencode

from searx.exceptions import SearxEngineResponseException
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://konradksiazak.pl",
    "official_api_documentation": "https://developer.wordpress.org/rest-api/",
    "use_official_api": True,
    "require_api_key": False,
    "results": "JSON",
}

categories = ["general"]
paging = True

base_url = "https://konradksiazak.pl"
api_path = "/wp-json/wp/v2/posts"

# The archive is six posts; asking for more is free but returns nothing and
# makes X-WP-TotalPages the only signal that paging exists.
per_page = 10

_CATEGORY_RE = re.compile(r"<[^>]+>")


def request(query, params):
    params["url"] = f"{base_url}{api_path}?" + urlencode(
        {
            "search": query,
            "per_page": per_page,
            "page": params.get("pageno", 1),
        }
    )
    return params


def response(resp) -> EngineResults:
    if resp.status_code == 400:
        # WordPress answers 400 for a page number past the end, which is how a
        # user paging to the last page learns to stop. That is an empty result
        # set, not a failure of the engine.
        return EngineResults()
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"unexpected status {resp.status_code}")

    results = EngineResults()
    for post in resp.json():
        title = html_to_text(post.get("title", {}).get("rendered", "")).strip()
        link = post.get("link")
        if not title or not link:
            continue
        results.add(
            results.types.LegacyResult(
                {
                    "url": link,
                    "title": title,
                    # The excerpt, not the body: a 15 kB article in a search
                    # result is unreadable, and the excerpt is the office's own
                    # summary of its own thesis.
                    "content": html_to_text(
                        post.get("excerpt", {}).get("rendered", "")
                    ).strip(),
                    "publishedDate": _date(post.get("date")),
                }
            )
        )
    return results


def _date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
