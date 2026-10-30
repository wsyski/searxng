# SPDX-License-Identifier: AGPL-3.0-or-later
"""Aktienyheterna (aktienyheterna.se)

A Swedish retail-equity blog publishing per-company notes and report
write-ups for Stockholm-listed names — the Swedish counterpart of what
:py:mod:`searx.engines.ksiazak` is for Poland: a small archive whose value is
coverage of a *name you hold*, not volume.

The public WordPress REST API is the intended way in, so this engine reads
JSON from it rather than scraping the ``?s=`` page::

    https://www.aktienyheterna.se/wp-json/wp/v2/posts?search=<terms>&page=<n>

.. attention::

   **``search`` matches a SUBSTRING of the body, so ``response()`` filters.**
   This is the trap, measured 2026-10-30: ``?search=granges`` returns two
   posts, and *neither is about Gränges*. Both are Spendrups sustainability
   write-ups that mention **Grängesberg**, the Dalarna town where the brewery
   was founded — ``granges`` is a substring of ``grangesberg``. For a portfolio
   consumer asking "has anyone written about Gränges", two confident rows about
   a brewery are worse than no rows at all: a gap is visible, a false hit reads
   as coverage.

   The engine therefore keeps a row only when **every** query term appears as a
   whole word — no alphanumeric character immediately before or after — in the
   folded title, excerpt or body. Measured yield 2026-10-30, site rows → kept:
   ``granges`` 2 → 0, ``swedbank`` 10 → 10, ``cloetta`` 3 → 3,
   ``castellum`` 10 → 9, ``telia`` 10 → 10, ``apotea`` 3 → 3. The one dropped
   Castellum row is the filter doing its job on a partial match.

   The body is fetched (``content`` in ``_fields``) rather than filtering on
   title and excerpt alone, because a body-only mention is a legitimate hit —
   the same property :py:mod:`searx.engines.ksiazak` relies on, where a note
   about one company discusses another inside it. Narrowing the haystack to the
   title would turn those into misses.

.. attention::

   **The HTML ``?s=`` page is not a better source and its row count misleads.**
   Measured 2026-10-30, distinct ``/blog/`` links on ``/?s=<q>``: a nonsense
   query already returns **5** (sidebar "recent posts" furniture), ``granges``
   7, ``cloetta`` 8, ``swedbank`` 15 — i.e. exactly the REST yield plus a fixed
   noise floor of five. Counting raw occurrences of the term in that page is
   higher still, because the search box echoes the query. The REST API gives
   the same corpus with no furniture to subtract.

``_fields`` is set explicitly: without it ``content.rendered`` arrives wrapped
in a per-post ``<style>`` blob, and the response for ten posts is several times
larger for nothing. ``X-WP-Total``/``X-WP-TotalPages`` are exposed by CORS
headers but not needed — WordPress answers **400** past the last page, which
:py:func:`response` treats as an empty result set rather than a failure.

No ``User-Agent`` is set for authentication reasons — the API answers every
client identically — but one is sent anyway, honestly, for the same reason
:py:mod:`searx.engines.sii` does. robots.txt (checked 2026-10-30) carries no
AI-agent rule and no TDM reservation; ``/.well-known/tdmrep.json`` is 404 and
the pages carry no ``tdm-reservation`` meta. ``User-agent: *`` disallows only
``/wp-admin/``.
"""

import re
import unicodedata
from datetime import datetime
from urllib.parse import urlencode

from searx.exceptions import SearxEngineResponseException
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://www.aktienyheterna.se",
    "official_api_documentation": "https://developer.wordpress.org/rest-api/",
    "use_official_api": True,
    "require_api_key": False,
    "results": "JSON",
}

categories = ["finance", "finance-sweden"]
paging = True

base_url = "https://www.aktienyheterna.se"
api_path = "/wp-json/wp/v2/posts"

per_page = 10

# Only what response() reads. Omitting this ships every field WordPress has,
# including a per-post <style> blob inside content.rendered.
fields = "id,date_gmt,link,title,excerpt,content"

headers = {"User-Agent": "SearXNG/1.0"}

# NFKD decomposes å/ä/ö into base + combining mark, but ø and æ are letters of
# their own and survive it — so without this table "Bøhler" never matches
# "bohler". ł/Ł is here for the same reason in sii.py and equity_news.py.
_FOLD_EXTRA = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ł": "l", "Ł": "l"})

_TAG_RE = re.compile(r"<[^>]+>")


def _fold(text):
    text = (text or "").translate(_FOLD_EXTRA)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _terms(query):
    return [t for t in _fold(query).split() if t]


def _whole_word(term, haystack):
    """``term`` in ``haystack`` with no alphanumeric neighbour on either side.

    Not ``\\b``: the term can itself end in a non-word character (a ticker
    written ``ERIC-B``), where ``\\b`` anchors on the wrong side and the test
    passes for any suffix. Explicit lookarounds say which characters are
    forbidden rather than relying on what counts as a word boundary.
    """
    return re.search(r"(?<![0-9a-z])" + re.escape(term) + r"(?![0-9a-z])", haystack) is not None


def request(query, params):
    params["url"] = f"{base_url}{api_path}?" + urlencode(
        {
            "search": query,
            "per_page": per_page,
            "page": params.get("pageno", 1),
            "_fields": fields,
        }
    )
    params["headers"].update(headers)
    return params


def response(resp) -> EngineResults:
    results = EngineResults()

    if resp.status_code == 400:
        # WordPress answers 400 for a page past the end, which is how a user
        # paging to the last page learns to stop. An empty result set, not a
        # failure — and it still publishes its counts, so a consumer can tell
        # "the engine ran and found nothing" from "the engine did not run".
        return _with_counts(results, dropped=0)
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"unexpected status {resp.status_code}")

    terms = _terms(resp.search_params.get("query", ""))
    dropped = 0
    seen = set()

    for post in resp.json():
        title = html_to_text(post.get("title", {}).get("rendered", "")).strip()
        link = post.get("link")
        if not title or not link or link in seen:
            continue
        seen.add(link)

        excerpt = html_to_text(post.get("excerpt", {}).get("rendered", "")).strip()

        # The body is part of the haystack, not of the result: a 15 kB article
        # in a search row is unreadable, and the excerpt is the author's own
        # summary. See the docstring — "granges" matching "Grängesberg" is why
        # there is a filter at all, and a body-only mention is why it reads the
        # body to decide.
        body = _TAG_RE.sub(" ", post.get("content", {}).get("rendered", "") or "")
        haystack = _fold(" ".join((title, excerpt, body)))
        if any(not _whole_word(t, haystack) for t in terms):
            dropped += 1
            continue

        results.add(
            results.types.LegacyResult(
                {
                    "url": link,
                    "title": title,
                    "content": excerpt,
                    "publishedDate": _date(post.get("date_gmt")),
                }
            )
        )

    return _with_counts(results, dropped)


def _with_counts(results: EngineResults, dropped: int) -> EngineResults:
    """Publish the filter's cost through ``engine_data``, on every path.

    The counts are the engine's own answer to "did you run?". A query whose
    only rows were partial matches comes back empty, and from outside "empty"
    and "correctly filtered" are the same thing; an engine that was dropped or
    suspended contributes no ``engine_data`` key at all, so the key's presence
    is itself the statement that this engine ran. ``general.debug`` is false on
    the deployed instance, so a ``logger.debug`` would not be written — the
    consumer reads the JSON response, not this instance's log.
    """
    kept = len(results)
    results.add(results.types.LegacyResult(engine_data=str(dropped), key="dropped_rows"))
    results.add(results.types.LegacyResult(engine_data=str(dropped + kept), key="site_rows"))
    if dropped:
        logger.debug("dropped %d of %d row(s): partial-word match only", dropped, dropped + kept)
    return results


def _date(value):
    if not value:
        return None
    try:
        # date_gmt has no offset; WordPress documents it as UTC.
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
