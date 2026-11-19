# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bing-News: description see :py:obj:`searx.engines.bing`.

.. hint::

   Bing News is *different* in some ways!

Fork-local change: Bing shows each item's age only as display text, in the
market's language ("2 hours ago", "Vor 2 Tagen", "for 1 dag siden", "29.10.2026",
"2026-10-23", "03/11/2026"), and upstream passes it on as ``metadata`` alone, so
no Bing News row carried a ``publishedDate``. A client filtering news by date
(the portfolio's DSA gateway and trading-agents web news) then dropped every
undated row, which for Polish listings was nearly all of them (2026-11-19).
:py:func:`published_date` reads that text; ``metadata`` is unchanged.

"""

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from searx.enginelib.traits import EngineTraits
from searx.engines.bing import get_locale_params
from searx.utils import eval_xpath, eval_xpath_getindex, eval_xpath_list, extract_text

# about
about = {
    "website": "https://www.bing.com/news",
    "wikidata_id": "Q2878637",
    "official_api_documentation": "https://github.com/MicrosoftDocs/bing-docs",
    "use_official_api": False,
    "require_api_key": False,
    "results": "RSS",
}

# engine dependent config
categories = ["news"]
paging = True
"""If go through the pages and there are actually no new results for another
page, then bing returns the results from the last page again."""
enable_http3 = True

time_range_support = True
time_map = {
    "day": 'interval="4"',
    "week": 'interval="7"',
    "month": 'interval="9"',
}
"""A string '4' means *last hour*.  We use *last hour* for ``day`` here since the
difference of *last day* and *last week* in the result list is just marginally.
Bing does not have news range ``year`` / we use ``month`` instead."""

base_url = "https://www.bing.com"
"""Bing (News) search URL"""

# Unit words by prefix, in the languages Bing News answers in. Order matters:
# "min" before the hour words, so "minuty"/"minuten" are minutes.
_UNITS = (
    ("minutes", ("min",)),
    ("hours", ("hour", "stund", "std", "timm", "time", "heure", "godz", "hora", "ora", "ore", "uur")),
    ("days", ("day", "tag", "dag", "dage", "jour", "dni", "dzie", "día", "dia", "giorn")),
    ("weeks", ("week", "woch", "veck", "uke", "uge", "semaine", "tydz", "tygod", "semana", "settiman")),
    ("months", ("month", "monat", "månad", "måned", "mois", "miesi", "mes", "maand")),
)
_ONE = {"a", "an", "one", "ein", "eine", "einem", "einer", "un", "une", "en", "ett", "et", "jeden", "uno", "una"}
_YESTERDAY = ("yesterday", "gestern", "igår", "i går", "wczoraj", "hier", "ayer", "ieri", "gisteren")
_TODAY = ("today", "heute", "idag", "i dag", "dzisiaj", "aujourd", "hoy", "oggi", "vandaag")
_TOKENS = re.compile(r"\d+|[^\W\d_]+")
_YMD = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY_DOT = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_EN_NAMED = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y")


def _date(year, month, day):
    try:
        return datetime(int(year), int(month), int(day))
    except ValueError:
        return None


def published_date(label, locale="", now=None):  # pylint: disable=too-many-return-statements,too-many-branches
    """The item's date from Bing's age label, or None when the text is not one.

    Slash dates are day first except in a US-English market, unless a part over 12
    settles it."""
    now = now or datetime.now()
    text = (label or "").strip()
    low = text.lower()
    if not low:
        return None
    if any(w in low for w in _YESTERDAY):
        return now - timedelta(days=1)
    if any(w in low for w in _TODAY):
        return now
    m = _YMD.search(text)
    if m:
        return _date(*m.groups())
    m = _DMY_DOT.search(text)
    if m:
        return _date(m.group(3), m.group(2), m.group(1))
    m = _SLASH.search(text)
    if m:
        a, b, y = (int(g) for g in m.groups())
        us = locale.lower() in ("en", "en-us")
        if (us and a <= 12) or b > 12:
            a, b = b, a
        return _date(y, b, a)
    for fmt in _EN_NAMED:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    tokens = _TOKENS.findall(low)
    for count, word in zip(tokens, tokens[1:]):
        if count.isdigit():
            n = int(count)
        elif count in _ONE:
            n = 1
        else:
            continue
        for unit, prefixes in _UNITS:
            if word.startswith(prefixes):
                if unit == "months":
                    return now - timedelta(days=30 * n)
                return now - timedelta(**{unit: n})
    return None


def request(query, params):
    """Assemble a Bing-News request."""

    engine_region = traits.get_region(params["searxng_locale"], traits.all_locale)

    # build URL query
    # - example: https://www.bing.com/news/infinitescrollajax?q=london&first=1
    page = int(params.get("pageno", 1)) - 1
    query_params = {
        "q": query,
        "InfiniteScroll": 1,
        # to simplify the page count lets use the default of 10 images per page
        "first": page * 10 + 1,
        "SFX": page,
        "form": "PTFTNR",
    }

    locale_params = get_locale_params(engine_region)
    if locale_params:
        query_params.update(locale_params)

    if params["time_range"]:
        query_params["qft"] = time_map.get(params["time_range"], 'interval="9"')

    params["url"] = base_url + "/news/infinitescrollajax?" + urlencode(query_params)


def response(resp):
    """Parse the Bing-News response."""

    results = []

    dom = resp.html()

    for newsitem in eval_xpath_list(dom, '//div[contains(@class, "newsitem")]'):
        link = eval_xpath_getindex(newsitem, './/a[@class="title"]', 0, None)
        if link is None:
            continue
        url = link.attrib.get("href")
        title = extract_text(link)
        content = extract_text(eval_xpath(newsitem, './/div[@class="snippet"]'))

        metadata = []
        published = None
        source = eval_xpath_getindex(newsitem, './/div[contains(@class, "source")]', 0, None)
        if source is not None:
            age = eval_xpath_getindex(source, ".//span[@aria-label]/@aria-label", 0, None)
            if age is not None:
                published = published_date(
                    extract_text(age), (getattr(resp, "search_params", None) or {}).get("searxng_locale", "")
                )
            for item in (
                age,
                # eval_xpath_getindex(source, './/a', 0, None),
                # eval_xpath_getindex(source, './div/span', 3, None),
                link.attrib.get("data-author"),
            ):
                if item is not None:
                    t = extract_text(item)
                    if t and t.strip():
                        metadata.append(t.strip())
        metadata = " | ".join(metadata)

        thumbnail = None
        imagelink = eval_xpath_getindex(newsitem, './/a[@class="imagelink"]//img', 0, None)
        if imagelink is not None:
            thumbnail = imagelink.attrib.get("src")
            if not thumbnail.startswith("https://www.bing.com"):
                thumbnail = "https://www.bing.com/" + thumbnail

        result = {
            "url": url,
            "title": title,
            "content": content,
            "thumbnail": thumbnail,
            "metadata": metadata,
        }
        if published is not None:
            result["publishedDate"] = published
        results.append(result)

    return results


def fetch_traits(engine_traits: EngineTraits):
    """Fetch languages and regions from Bing-News."""
    # pylint: disable=import-outside-toplevel

    from searx.engines.bing import fetch_traits as _f

    _f(engine_traits)

    # fix market codes not known by bing news:

    # In bing the market code 'zh-cn' exists, but there is no 'news' category in
    # bing for this market.  Alternatively we use the the market code from Honk
    # Kong.  Even if this is not correct, it is better than having no hits at
    # all, or sending false queries to bing that could raise the suspicion of a
    # bot.

    # HINT: 'en-hk' is the region code it does not indicate the language en!!
    engine_traits.regions["zh-CN"] = "en-hk"
