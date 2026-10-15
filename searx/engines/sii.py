# SPDX-License-Identifier: AGPL-3.0-or-later
"""SII — Stowarzyszenie Inwestorów Indywidualnych (sii.org.pl)

Poland's largest individual-investor association. It publishes per-company
commentary ("Spółka tygodnia"), broker and fund notes, and its own periodic
investor surveys — the kind of write-up that names a GPW ticker in the title,
which is what makes it searchable rather than a feed to read end to end.

The site has a plain server-rendered search page::

    https://www.sii.org.pl/szukaj?search=<terms>

.. attention::

   **The parameter is ``search``, not ``q``.** ``/szukaj?q=...`` returns
   HTTP 200 and the *same 62 kB page for every query* — including a nonsense
   one — so a wrong parameter name reads as "the engine is up and found
   nothing" rather than as a failure. Verified 2026-10-11: ``?q=orlen``,
   ``?q=cdprojekt`` and ``?q=zzzqqqxx`` each returned 62,576 bytes; the same
   terms with ``?search=`` returned 87,783, 84,067 and 62,846. The last is the
   genuine no-results baseline, so a real result set is distinguishable from
   an ignored parameter only by size.

.. attention::

   **A realistic ``User-Agent`` is required, and any realistic one works.**
   Re-measured 2026-10-11 with status codes, which an earlier pass in this file
   got wrong — it recorded a small body as "an empty shell" when it was in fact a
   403: no ``User-Agent``, a bare ``Mozilla/5.0`` and ``curl/8.5.0`` each answer
   **403** with ~5.4 kB, while ``SearXNG/1.0`` and
   ``Mozilla/5.0 (compatible; searxng)`` both answer **200** with 87,783 bytes
   and 10 results.

   The engine therefore sets its own UA rather than leaning on SearXNG's default
   curl_cffi browser impersonation. That is the better trade twice over: the site
   is happy to be told exactly what it is talking to, and the engine keeps working
   if impersonation is ever turned off. No page here needs a *browser* — it needs
   a client that identifies itself.

.. attention::

   **The site rate-limits hard, and the engine says so.** A burst of eight
   searches to ``/szukaj`` was served twice and then answered **429** for the
   rest. Raising the generic response exception made SearXNG report that as
   ``unexpected crash`` in ``unresponsive_engines``, which is the opposite of what
   happened; the engine now raises
   :py:class:`searx.exceptions.SearxEngineTooManyRequestsException`, which renders
   as "too many requests" and suspends the engine for an hour so the burst is not
   repeated. A Postman run of four SII requests back to back can trip this; the
   integration collection encodes that as an accepted second outcome rather than
   hiding it.

   robots.txt (checked 2026-10-11) carries no AI-agent rule of any kind; the
   ``User-agent: *`` group disallows only ``/cgi-bin/``, ``/min/``, ``/pimg/``,
   ``/weryfikacja/``, ``/images/`` and ``/scripts/``, none of which this
   engine touches.

.. attention::

   **The site ORs the terms and matches fragments, so `response()` filters.**
   Measured on the live site from the host, 2026-10-15, one ``/szukaj`` page
   each (the count of ``class="newsabout"`` blocks):

   ====================  =======
   ``?search=``          results
   ====================  =======
   ``zzqxv``             0 (404)
   ``zzqxv+term``        10
   ``term``              10
   ====================  =======

   ``zzqxv term`` and ``term`` return the *same* ten rows — the site keeps
   whichever term matched, so a nonsense word costs nothing. Through this engine
   that put ten unrelated rows into every default search: ``sii`` is in
   ``general``, so on ``q=ECB interest rate`` it contributed 10 of 96 results.
   Because the OR happens server-side it cannot be fixed by the query; the only
   place that sees both the query (``resp.search_params["query"]``) and the row
   is ``response()``, which therefore keeps a row only when **every** query term
   appears in its title or teaser, compared case- and diacritic-insensitively.

   The accepted cost is a missed hit whose title and teaser use a synonym or
   abbreviation of a query term (``PKN`` for ``Orlen``). A gap is visible; a
   false hit reads as coverage, which is the worse failure.

The result markup carries one ``<div class="newsabout">`` per hit, holding an
``<h3>`` anchor (title and URL), a date and author line, and a teaser
paragraph. Adverts are interleaved as ``click.php?rid=...`` links inside
``mustsee``/``adshold`` wrappers; the article-URL pattern below excludes them,
and it also excludes the ``/autor/<name>.html`` author links that share the
same block.

``/szukaj`` accepts no paging: ``strona=2`` returns byte-identical output and
the page contains no pagination links, so paging is disabled rather than
offered and then found to be broken.
"""

import re
import unicodedata
from datetime import datetime
from urllib.parse import urlencode

from searx.exceptions import (
    SearxEngineAccessDeniedException,
    SearxEngineResponseException,
    SearxEngineTooManyRequestsException,
)
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://www.sii.org.pl",
    "official_api_documentation": None,
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["news", "general"]
paging = False

base_url = "https://www.sii.org.pl"

# Set explicitly, and honestly. See the module docstring: a bare
# "Mozilla/5.0" and "curl/8.5.0" are answered 403, while "SearXNG/1.0" gets the
# full page. Overriding here also survives impersonation being disabled.
headers = {"User-Agent": "SearXNG/1.0"}

# One result block. Split on the wrapper class rather than trying to walk the
# surrounding ad furniture, which also contains anchors.
_BLOCK_RE = re.compile(r'class="newsabout".*?(?=class="newsabout"|<div class="right page"|$)', re.S)

# An article URL is /<id>/<section>/<slug>.html. The id is what separates a
# result from an advert (click.php?rid=) or an author page (/autor/x.html).
_ARTICLE_RE = re.compile(r"^https://www\.sii\.org\.pl/(\d+)/[^\"]*\.html$")

_TITLE_RE = re.compile(r"<h3[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S)
# The date sits right after an empty <span class="calendar">.
_DATE_RE = re.compile(r'class="calendar"></span>\s*(\d{2})\.(\d{2})\.(\d{4})')
# EVERY <p> in the block, so the teaser can be picked by what it is rather than
# by a fixed class name. The two variants on this site disagree here: the
# comment carries its summary in <p class="above">, a news story carries it in
# <p class="notes">, and the date/author line is <p class="metas"> in both.
# Matching one class name silently emptied the summary for the other variant.
_P_RE = re.compile(r'<p class="([^"]*)"[^>]*>(.*?)</p>', re.S)
_META_CLASS = "metas"

# NFKD decomposes ó/ś/ż into base + combining mark, but Ł/ł is a letter of its own
# and survives untouched - so without this table "złoto" never matches "zloto".
_FOLD_EXTRA = str.maketrans({"ł": "l", "Ł": "l"})


def _fold(text):
    text = (text or "").translate(_FOLD_EXTRA)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _terms(query):
    return [t for t in _fold(query).split() if t]


def request(query, params):
    # `search`, never `q` — see the module docstring. urlencode, not an
    # f-string: `AT&T` interpolated raw becomes search=AT plus a stray `T`
    # parameter, and `C#` truncates the query at the fragment.
    params["url"] = f"{base_url}/szukaj?" + urlencode({"search": query})
    params["headers"].update(headers)
    # A query that matches nothing is answered 404, not 200-with-no-rows, and
    # SearXNG raises on an error status before response() ever runs. Left
    # alone, every miss would be reported as a broken engine rather than as an
    # engine that found nothing — the difference between "this engine is down"
    # and "nothing here matches", which is the distinction this whole module
    # docstring is about.
    params["raise_for_httperror"] = False
    return params


def response(resp) -> EngineResults:
    results = EngineResults()

    if resp.status_code == 404:
        return results
    # sii.org.pl rate-limits hard: measured 2026-10-11, a burst of eight searches
    # was served twice and then answered 429 for the rest. It is NOT a crash, and
    # raising the generic response exception made SearXNG label it "unexpected
    # crash" in unresponsive_engines — which says the opposite of what happened.
    # The dedicated exception renders as "too many requests" and, more usefully,
    # suspends this engine for an hour so the burst is not repeated.
    if resp.status_code == 429:
        raise SearxEngineTooManyRequestsException(message="sii.org.pl returned 429 (rate limited)")
    # The site answers 403 to a degenerate or absent User-Agent, which is a
    # configuration fault on our side rather than a block on SearXNG.
    if resp.status_code == 403:
        raise SearxEngineAccessDeniedException(message="sii.org.pl returned 403 (user agent refused)")
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"unexpected status {resp.status_code}")

    seen = set()
    terms = _terms(resp.search_params.get("query", ""))
    dropped = 0

    for block in _BLOCK_RE.findall(resp.text):
        m = _TITLE_RE.search(block)
        if not m:
            continue
        url, title = m.group(1), html_to_text(m.group(2)).strip()
        if not _ARTICLE_RE.match(url) or url in seen or not title:
            continue

        content = html_to_text(_teaser(block))

        haystack = _fold(title + " " + content)
        # sii.org.pl ORs the terms and matches fragments, so a row is ours only
        # if EVERY term is in what we can see of it. Measured 2026-10-15:
        # `zzqxv term` returned the same ten rows as `term`. See the docstring.
        if any(t not in haystack for t in terms):
            dropped += 1
            continue

        seen.add(url)

        results.add(
            results.types.LegacyResult(
                {
                    "url": url,
                    "title": title,
                    "content": content,
                    "publishedDate": _parse_date(block),
                }
            )
        )

    if dropped:
        # The filter's cost is otherwise invisible: a query whose rows all use a
        # synonym (`PKN` for `Orlen`) comes back empty, and "empty" and
        # "correctly filtered" look the same from outside. Debug, not warning -
        # a synonym miss is an accepted outcome of the design rather than a
        # fault, and a warning here would train people to ignore the ones that
        # matter. The query is named because it is the other half of the
        # question an operator is asking.
        logger.debug(
            "dropped %d of %d row(s): none carried every term of %r",
            dropped,
            dropped + len(results),
            resp.search_params.get("query", ""),
        )

    return results


def _teaser(block):
    """The summary paragraph, with the trailing 'Zobacz więcej' link cut off.

    The first <p> that is not the metas (date/author) line. Keyed on what it
    is not, so the two markup variants are both handled without naming either
    class. The membership test is a split, not an equality: one variant writes
    the date line as ``<p class="above metas">``, two classes on one element,
    so an exact match to "metas" misses it and returns the date as the summary.
    """
    for css_class, body in _P_RE.findall(block):
        if _META_CLASS in css_class.split():
            continue
        return re.split(r"<a\b", body)[0].strip()
    return ""


def _parse_date(block):
    m = _DATE_RE.search(block)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        # A date like 31.02 is a page error, not a crash.
        return None
