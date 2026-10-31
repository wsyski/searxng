# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stooq (stooq.com) — Polish market portal, news search

``/search/?q=`` is a **news** search over PAP items: ten rows per page, each a
title, a truncated teaser and a ``date - PAP`` line::

    https://stooq.com/search/?q=<terms>&l=<page>&type=nws

It is not an instrument search. Ticker lookup is ``/q/s/?e=<term>``, which
matches symbols only (``bank`` returns ``BANK.UK`` and nothing else), and
``/q/?s=<term>`` is a single quote page that answers "not in database" for
anything that is not a ticker. Neither is a general search source, so this
engine only wraps the news search.

The search form has three scopes — ``fll`` (whole site), ``nws`` (Wiadomości)
and ``nwsb`` (Biznes). This engine sends ``type=nws``: omitting the parameter
gets the whole-site default, which would put static pages into a ``news``
category. ``nwsb`` is the same PAP feed filtered to business and is not a
separate source.

.. attention::

   **``robots.txt`` forbids this engine.** ``stooq.com`` and ``stooq.pl`` both
   serve::

       User-agent: Bingbot
       Allow: /
       User-agent: Googlebot
       Allow: /
       User-agent: *
       Disallow: /

   This engine is **enabled, but in ``finance`` and ``finance poland`` only**.
   Its content is news; the categories keep it out of default ``general`` and
   ``news`` queries. ``finance`` is the international/general category and
   ``finance poland`` its Polish subset. The portfolio requests
   ``finance poland`` once per day, and the finance record is the job's
   once-a-day cap; a manual category query is an explicit request and is not
   capped by the job. Do not add it to ``news``.

.. attention::

   **Two gates, neither of them the User-Agent.** A request without cookies is
   answered with a 795-byte JavaScript proof-of-work challenge::

       const c="AAAA...", d=4
       ... crypto.subtle.digest("SHA-256", c + n) starts with "0000" ...
       fetch("/__verify", {body: "c=...&n=..."})  ->  Set-Cookie: auth=...

   Measured 2026-10-24: no UA, ``curl/8.5.0``, Chrome 140 and Firefox 158 all
   receive the identical 795-byte challenge, so a browser UA buys nothing and
   this engine does not pretend to be one. What gets through is executing the
   PoW and replaying the issued ``auth`` cookie. Solving is cheap: difficulty 4
   averages 65,536 SHA-256 evaluations (~0.1 s), and the result is cached.

   After ``auth`` is accepted the response is still **not** the site: it is a
   ~234 kB Google Funding Choices consent script with no visible text and no
   ``<title>``. The real page is served only when a ``privacy`` cookie is
   present. This engine sets ``privacy=1``, which is a consent cookie set
   **without consent** — the second reason this engine is opt-in and disabled
   by default. Both cookies are set explicitly on every search; the PoW is
   retried once in :py:func:`response` when a cached ``auth`` has expired.

.. attention::

   **A query with no matches is a 200 with an explicit empty state**, not a 404:
   ``Nie znaleziono szukanego wyrażenia``. That page is returned as zero
   results, not as an engine failure. The consent wall is detected separately:
   it carries neither that string nor ``Szukaj na Stooq``.

Paging: ``l`` is 1-based; ``l=2`` is the second page ("Następna >"). Dates are
Polish abbreviations (``20 sty 2026, 7:45``), mapped explicitly because
``strptime`` has no Polish month names under an English locale.
"""

import hashlib
import re
import typing as t
from datetime import datetime
from urllib.parse import urlencode

from searx.enginelib import EngineCache
from searx.exceptions import (
    SearxEngineCaptchaException,
    SearxEngineResponseException,
    SearxEngineTooManyRequestsException,
)
from searx.network import get, post
from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://stooq.com",
    "official_api_documentation": None,
    "use_official_api": False,
    "require_api_key": False,
    "results": "HTML",
}

categories = ["finance", "finance poland"]
paging = True

base_url = "https://stooq.com"

# One row: title in <font id=f16>, teaser plus `date - PAP` in the <font id=f13>
# that follows the same <br>. The markup is unquoted, so the pattern accepts a
# bare attribute value; requiring quotes matched nothing on the live page.
_ITEM_RE = re.compile(
    r'<font id=f16><a href="?(?P<url>n/\?f=\d+[^">]*)"?>(?P<title>.*?)</a></font>'
    r"\s*<br>\s*<font id=f13>(?P<body>.*?)</font>",
    re.S,
)

# The date line is the only span with class lc1 in a row: "20 sty 2026, 7:45 - PAP".
_DATE_RE = re.compile(r"<span class=lc1>(.*?)</span>", re.S)
_DATE_PARTS_RE = re.compile(r"(\d{1,2}) (\w{3}) (\d{4}), (\d{1,2}):(\d{2})")

# Polish three-letter month abbreviations, same trap as dna_rynkow.py: strptime
# under an English locale does not know them.
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

# The challenge as served: const c="...",d=4 — d is the number of leading hex
# zeros required of sha256(c + nonce). Measured at 4; refuse anything higher
# rather than burning CPU on a changed scheme.
_CHALLENGE_RE = re.compile(r'const c="(?P<challenge>[^"]+)",d=(?P<difficulty>\d+)')
_max_difficulty = 4

# A cached auth is a session cookie of unknown lifetime. It is reused until the
# site answers with a fresh challenge, and response() re-solves once when that
# happens; the TTL only bounds how long an unused cookie sits in the cache.
_auth_cache_sec = 3600 * 6

CACHE: EngineCache
"""Cached ``auth`` cookie from the proof-of-work gate."""


def setup(_: dict[str, t.Any]) -> bool | None:
    global CACHE  # pylint: disable=global-statement
    CACHE = EngineCache("stooq")
    return True


def request(query, params):
    # type=nws is the form's "Wiadomości" scope. Omitting it gets fll (the
    # whole site), which is not what a news-category engine should search.
    params["url"] = f"{base_url}/search/?" + urlencode({"q": query, "l": params.get("pageno", 1), "type": "nws"})
    params.setdefault("cookies", {})["privacy"] = "1"
    auth = CACHE.get("auth")
    if auth:
        params["cookies"]["auth"] = auth
    # 429 is turned into "too many requests" in response(); every other status
    # is checked there too, so this engine owns the diagnosis.
    params["raise_for_httperror"] = False
    return params


def response(resp) -> EngineResults:
    if _CHALLENGE_RE.search(resp.text):
        # The cached auth is stale (or absent): solve again and replay the
        # search once. The challenge token is bound to this request, not to the
        # cached cookie, so it has to come from this response.
        params = resp.search_params
        params.setdefault("cookies", {})["auth"] = _solve_pow(resp)
        resp = get(params["url"], headers=params.get("headers"), cookies=params["cookies"])
        if _CHALLENGE_RE.search(resp.text):
            raise SearxEngineCaptchaException(message="stooq: proof-of-work did not clear")

    if resp.status_code == 429:
        raise SearxEngineTooManyRequestsException(message="stooq.com returned 429 (rate limited)")
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"stooq: unexpected status {resp.status_code}")

    # Consent wall: neither marker is present on the 234 kB Google Funding
    # Choices document, so treating it as "no results" would hide the gate.
    if "Szukaj na Stooq" not in resp.text and "Nie znaleziono" not in resp.text:
        raise SearxEngineCaptchaException(message="stooq: consent wall")

    results = EngineResults()
    seen = set()
    for match in _ITEM_RE.finditer(resp.text):
        url = f"{base_url}/{match.group('url')}"
        if url in seen:
            continue
        seen.add(url)

        title = _text(match.group("title"))
        if not title:
            continue
        body = match.group("body")
        date_match = _DATE_RE.search(body)
        snippet = _text(_DATE_RE.sub(" ", body))

        results.add(
            results.types.LegacyResult(
                {
                    "url": url,
                    "title": title,
                    "content": snippet,
                    "publishedDate": _published(date_match.group(1) if date_match else None),
                }
            )
        )

    return results


def _solve_pow(resp) -> str:
    match = _CHALLENGE_RE.search(resp.text)
    if not match:
        raise SearxEngineCaptchaException(message="stooq: no proof-of-work challenge found")

    challenge = match.group("challenge")
    difficulty = int(match.group("difficulty"))
    if difficulty > _max_difficulty:
        raise SearxEngineCaptchaException(message=f"stooq: PoW difficulty {difficulty} is too high")

    prefix = "0" * difficulty
    for nonce in range(16**difficulty * 8):
        if hashlib.sha256((challenge + str(nonce)).encode()).hexdigest().startswith(prefix):
            break
    else:
        raise SearxEngineCaptchaException(message="stooq: proof-of-work failed")

    pass_resp = post(f"{base_url}/__verify", data={"c": challenge, "n": nonce})
    auth = pass_resp.cookies.get("auth")
    if not auth:
        raise SearxEngineCaptchaException(message="stooq: /__verify did not issue an auth cookie")
    auth = str(auth)
    CACHE.set("auth", auth, expire=_auth_cache_sec)
    return auth


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(fragment)).strip()


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    match = _DATE_PARTS_RE.search(value)
    if not match:
        return None
    day, month_abbr, year, hour, minute = match.groups()
    month = _MONTHS.get(month_abbr.lower())
    if month is None:
        return None
    try:
        return datetime(int(year), month, int(day), int(hour), int(minute))
    except ValueError:
        return None
