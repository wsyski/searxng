# SPDX-License-Identifier: AGPL-3.0-or-later
"""DNA Rynków (dnarynkow.pl)

A Polish investor-education site that maintains a per-company card for ~100
listed names — ``/spolki/<slug>/`` — carrying a plain-language description, the
ticker, the listing venue, the trading currency and a "Spółka tygodnia"-style
commentary index. For a GPW-heavy portfolio the card is the useful artefact: it
answers "who has written about the company I hold" in one query.

The site has no search *page*. It has a search *parameter*, on the stock index::

    https://dnarynkow.pl/spolki/?search=<terms>

.. attention::

   **Do not conclude "no search interface" from the sitemap.** There is no
   ``/szukaj``, no ``/search`` route, no WordPress REST API (WordPress is behind
   the Nuxt frontend and ``/wp-json/`` is 404) and no RSS feed — a sitemap lists
   *pages*, and a query parameter is not a page, so it does not appear in one.
   That reasoning is wrong and it was wrong here first: every probe that looked
   for a search path came back negative while ``?search=`` worked the whole time.

.. attention::

   **The results are in the HTML body, not in the ``__NUXT_DATA__`` payload.**
   The page is a Nuxt SPA and its hydration payload is ~2.5 kB and carries no
   stock data at all, so a check that decodes the payload concludes "client
   rendered, nothing here". The result rows are server-rendered into the body
   alongside it. Verified 2026-10-11: ``?search=alibaba`` and
   ``?search=zzzqqqxxnosuchterm`` differ in body size, and the body carries a
   live result count — ``(1)`` against ``(0)`` — plus an explicit empty state,
   ``Nie znaleziono spółek dla podanych parametrów``.

The page needs no ``User-Agent``: a request with none, a bare ``Mozilla/5.0``
and ``curl/8.5.0`` all return the same result set, so this engine sets no
headers and relies on the default transport.

``robots.txt`` (checked 2026-10-11) is explicit rather than silent — it names
GPTBot, OAI-SearchBot, ChatGPT-User, **ClaudeBot, Claude-User,
Claude-SearchBot**, PerplexityBot, Google-Extended, Applebot-Extended,
Amazonbot, CCBot and meta-externalagent under ``Allow: /``. The only path
disallowed is ``/pulpit``, which this engine never requests.

Paging: 24 results per page. The ``page`` parameter is 1-based in effect —
``page=1`` and ``page=0`` both return the first page, ``page=2`` the second.
Checked with ``?search=a``, which reports 56 matches and returns 24 + 24 + 8.

.. attention::

   **Coverage is partial and that is not the engine's fault.** Orlen — the
   second-largest GPW weight in one portfolio — has no card and returns zero
   results. The list skews toward growth and US-listed names, so this answers
   "is this company covered" and not "is this company analysed".
"""

import re
from datetime import datetime

from searx.exceptions import SearxEngineResponseException
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://dnarynkow.pl",
    "official_api_documentation": None,
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["news"]
paging = True

base_url = "https://dnarynkow.pl"

# One result card: a link to the stock page carrying the name + ticker heading,
# the "Aktualizacja:" line, and the exchange/currency badges. Matched with
# finditer, not findall: the pattern has a capture group, and findall returns
# the GROUP rather than the whole match, so every card arrived as a bare
# "/spolki/<slug>/" with none of the text the parser then looks for.
_ITEM_RE = re.compile(
    r'<a href="(?P<url>/spolki/[a-z0-9-]+/)"[^>]*class="flex flex-col gap-3 flex-1'
    r".*?</a>",
    re.S,
)
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_TICKER_RE = re.compile(r"\(([A-Z0-9.\-]{1,8})\)")
_UPDATED_RE = re.compile(r"Aktualizacja:\s*(\d{1,2})\s+(\w{3})\s+(\d{4})")
_BADGE_RE = re.compile(r'<span data-slot="label"[^>]*>([^<]+)</span>')

# "Aktualizacja: 25 cze 2026" — Polish three-letter month abbreviations, which
# do not survive strptime under an English locale, hence the explicit map.
_MONTHS = {
    "sty": 1,
    "lut": 2,
    "mar": 3,
    "kwi": 4,
    "maj": 5,
    "cze": 6,
    "lip": 7,
    "sie": 8,
    "wrz": 9,
    "paź": 10,
    "lis": 11,
    "gru": 12,
}


def request(query, params):
    # `search`, on the stock index. There is no search page to link to.
    page = params.get("pageno", 1)
    params["url"] = f"{base_url}/spolki/?search={query}&page={page}"
    return params


def response(resp) -> EngineResults:
    results = EngineResults()

    if resp.status_code != 200:
        raise SearxEngineResponseException(f"unexpected status {resp.status_code}")

    seen = set()
    for match in _ITEM_RE.finditer(resp.text):
        card = match.group(0)
        url = base_url + match.group("url")
        if url in seen:
            continue

        title = _title(card)
        if not title:
            continue
        seen.add(url)

        venue, currency = _badges(card)
        bits = [b for b in (venue, currency, _updated(card)) if b]
        results.add(
            results.types.LegacyResult(
                {
                    "url": url,
                    "title": title,
                    # The card carries no prose in the list view — the description
                    # lives on the page itself — so the badges are the summary.
                    "content": " · ".join(bits),
                    "publishedDate": _published(card),
                    "metadata": [k for k in (venue, currency) if k],
                }
            )
        )

    return results


def _title(card):
    m = _H3_RE.search(card)
    if not m:
        return ""
    return re.sub(r"\s+", " ", html_to_text(m.group(1))).strip()


def _ticker(card):
    m = _TICKER_RE.search(_H3_RE.search(card).group(1)) if _H3_RE.search(card) else None
    return m.group(1) if m else None


def _badges(card):
    """The first two badges are the listing venue and the trading currency."""
    labels = [b.strip() for b in _BADGE_RE.findall(card) if b.strip()]
    venue = labels[0] if labels else None
    currency = labels[1] if len(labels) > 1 else None
    return venue, currency


def _updated(card):
    m = _UPDATED_RE.search(card)
    if not m:
        return None
    return "updated {}/{}/{}".format(m.group(1), m.group(2), m.group(3))


def _published(card):
    m = _UPDATED_RE.search(card)
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    try:
        return datetime(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None
