# SPDX-License-Identifier: AGPL-3.0-or-later
"""Placera (placera.se)

Avanza's editorial site: Swedish market news, broker commentary
(``/nyheter``), equity analysis (``/analys``) and the full press-release wire
(``/pressmeddelanden``). Its archive goes back to 2006, which makes it the one
Swedish source in this set that can answer "has anyone ever written about this
holding" rather than only "this week".

The search is server-rendered on a Next.js page::

    https://www.placera.se/search?q=<terms>

.. attention::

   **The path is ``/search``, not ``/sok``.** Measured 2026-10-30:
   ``/sok?q=``, ``/sok/<q>`` and ``/soek?q=`` all answer **404** with a ~35 kB
   app shell, and ``/api/search`` answers **200** with
   ``{"articles":[],"authors":[],"tags":[]}`` for *every* parameter name tried
   (``query``, ``q``, ``s``, ``term``, ``searchTerm``, ``text``) — a JSON
   endpoint that is always empty and never an error, which is the worst of the
   three failure shapes because it looks like a working API.

.. attention::

   **The site matches fuzzily, so ``response()`` filters.** Measured
   2026-10-30, rows parsed off one ``/search`` page: ``swedbank`` 100,
   ``cloetta`` 100, ``granges`` 96, and the nonsense query ``zzqxvv`` **1** —
   a press release titled "ROK Drinks re-brands as ROKiT Drinks". The
   ``granges`` page carries press releases about *grants* and board *changes*,
   so the engine is not returning the term's hits, it is returning a ranked
   list that starts with them and trails off into near-misses.

   A row is therefore kept only when **every** query term appears as a whole
   word in its folded title or URL slug. The slug is in the haystack because it
   is the only other text the result row carries — the page has no teaser — and
   it is a transliteration of the title, so it costs nothing and catches a
   title that renders the name with a typographic apostrophe (``Gränges’``).

.. attention::

   **There is no paging.** ``&page=2``, ``&p=2`` and ``&offset=100`` each
   return the same first row and the same 100-row page, so paging is disabled
   rather than offered and then found to be a no-op. 100 rows is the page's own
   cap.

The date is taken from the **slug**, not from the rendered page: the displayed
date reads "30 september, 10:00" with no year, which for a 2006 archive is
useless. Editorial slugs end ``-YYYY-MM-DD`` and wire slugs ``-YYYYMMDD``.

robots.txt, checked 2026-10-30, and the verdict it supports:

- the ``User-agent: *`` group is ``Allow: /`` with ``Disallow: /admin/``.
- a second group names ``ClaudeBot``, ``Anthropic-ai``, ``GPTBot``,
  ``CCBot``, ``PerplexityBot``, ``Google-Extended``, ``Bytespider`` and others,
  and disallows only ``/_next/image``, ``/media/`` and ``/api/media/file/``.
  A named group *replaces* ``*`` rather than adding to it, so even under the
  AI-bot group ``/search`` is allowed; this engine touches none of the three
  disallowed prefixes under either group.
- the engine identifies as ``SearXNG/1.0``, which matches no named group and
  so falls under ``Allow: /``.
- no TDM reservation: ``/.well-known/tdmrep.json`` is 404, no
  ``tdm-reservation`` meta and no ``X-Robots-Tag`` on the search response.

This is deliberately *unlike* :py:mod:`searx.engines.stooq`, whose robots.txt
is ``Disallow: /`` for everyone and whose inclusion was the operator's explicit
decision. Nothing here needed one.

Two Swedish sources were considered and rejected, recorded so they are not
rediscovered as candidates:

- ``mfn.se`` (``Disallow: *.rss$``), ``di.se`` and ``privataaffarer.se``
  (Bonnier: ClaudeBot blocked, §15a TDM reservation) — a decision for the
  operator, like stooq, not for an engine author.
- ``aktiespararna.se/sok?q=`` — the sii ``?q=`` trap exactly: 200 for every
  query, 234,7xx bytes and the same five term occurrences for ``granges``,
  ``swedbank`` and a nonsense query, because the search is client-side and the
  page carries no results. Its backing API is not named anywhere in the markup
  (no algolia/typesense/elastic string), so there is nothing to call.
- ``borsvarlden.se`` — TLS: the certificate carries no name matching
  ``www.borsvarlden.se``.
"""

import re
import unicodedata
from datetime import datetime
from urllib.parse import urlencode

from searx.exceptions import SearxEngineResponseException
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://www.placera.se",
    "official_api_documentation": None,
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["finance", "finance sweden"]
# See the docstring: page/p/offset are all no-ops, so this is False rather
# than True-and-broken.
paging = False

base_url = "https://www.placera.se"

headers = {"User-Agent": "SearXNG/1.0"}

# One result row. The anchor is keyed on `class="group" tabindex="-1"` wrapping
# an <h3>, which is what every row has and what no navigation link, category
# chip or breadcrumb in the surrounding Tailwind soup has. Matching on the
# class salad itself would break on the next style tweak.
_ROW_RE = re.compile(r'<a class="group" tabindex="-1" href="(/[^"]+)">\s*<h3[^>]*>(.*?)</h3>', re.S)

# Editorial slug: ...-2026-10-22. Wire slug: ...-20261022.
_SLUG_DATE_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})$|-(\d{4})(\d{2})(\d{2})$")

# ø/æ are letters of their own and survive NFKD; å/ä/ö do not. Same table as
# aktienyheterna.py, for the same reason.
_FOLD_EXTRA = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ł": "l", "Ł": "l"})


def _fold(text):
    text = (text or "").translate(_FOLD_EXTRA)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _terms(query):
    return [t for t in _fold(query).split() if t]


def _whole_word(term, haystack):
    """``term`` in ``haystack`` with no alphanumeric neighbour on either side.

    Lookarounds rather than ``\\b``, so a term that itself ends in a non-word
    character (``ERIC-B``) is not matched against any suffix.
    """
    return re.search(r"(?<![0-9a-z])" + re.escape(term) + r"(?![0-9a-z])", haystack) is not None


def request(query, params):
    # urlencode, not an f-string: `AT&T` interpolated raw becomes q=AT plus a
    # stray `T` parameter, and `C#` truncates the query at the fragment.
    params["url"] = f"{base_url}/search?" + urlencode({"q": query})
    params["headers"].update(headers)
    return params


def response(resp) -> EngineResults:
    results = EngineResults()

    if resp.status_code != 200:
        raise SearxEngineResponseException(f"unexpected status {resp.status_code}")

    terms = _terms(resp.search_params.get("query", ""))
    dropped = 0
    seen = set()

    for path, raw_title in _ROW_RE.findall(resp.text):
        title = html_to_text(raw_title).strip()
        if not title or path in seen:
            continue
        # Counted before the relevance filter: the page repeats a row (the
        # 2026-10-30 `swedbank` page carried "Swedbank rapporterar som väntat"
        # twice), and one article rejected twice would put a number in
        # engine_data the page does not support.
        seen.add(path)

        # Title AND slug: the page gives a row no teaser, and the slug is a
        # transliteration of the title, so it catches "Gränges’ Nomination
        # Committee" where the apostrophe is typographic.
        haystack = _fold(title + " " + path.replace("-", " ").replace("/", " "))
        if any(not _whole_word(t, haystack) for t in terms):
            dropped += 1
            continue

        results.add(
            results.types.LegacyResult(
                {
                    "url": f"{base_url}{path}",
                    "title": title,
                    "content": "",
                    "publishedDate": _slug_date(path),
                }
            )
        )

    kept = len(results)
    # On every path, zero kept included: an engine that ran and filtered
    # everything is not an engine that did not run, and from outside the two
    # are the same empty result list. See aktienyheterna._with_counts.
    results.add(results.types.LegacyResult(engine_data=str(dropped), key="dropped_rows"))
    results.add(results.types.LegacyResult(engine_data=str(dropped + kept), key="site_rows"))

    if dropped:
        logger.debug(
            "dropped %d of %d row(s): the site ranks near-misses into the page",
            dropped,
            dropped + kept,
        )

    return results


def _slug_date(path):
    m = _SLUG_DATE_RE.search(path)
    if not m:
        return None
    groups = [g for g in m.groups() if g is not None]
    year, month, day = (int(g) for g in groups)
    try:
        return datetime(year, month, day)
    except ValueError:
        # A slug ending -20261340 is a publisher's typo, not a crash.
        return None
