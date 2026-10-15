# SPDX-License-Identifier: AGPL-3.0-or-later
"""Liferay forum (discuss.liferay.com)

The community forum runs on `Discourse <https://www.discourse.org>`_, whose
read-only search endpoint returns JSON::

    https://discuss.liferay.com/search.json?q=<terms>

Discourse does not expose an absolute URL on a topic, it only carries ``slug``
and ``id``, so the generic :ref:`json engine <json_engine engine>` cannot build
the link and a small engine is needed.

.. attention::

   Discourse rate-limits clients that do not look like a browser (a bare
   ``curl``/``requests`` User-Agent gets ``429``).  SearXNG sends its requests
   through curl_cffi with browser impersonation, so no explicit User-Agent is
   set here.

   ``/search.json`` accepts a ``page`` argument, but it returns the same result
   set for page 0 and page 1, so paging is disabled rather than offered and
   then found to be broken.

.. attention::

   Discourse rate-limits anonymous clients hard. A burst of searches gets the
   client suspended for 180 s, which SearXNG surfaces in ``unresponsive_engines``
   as ``Suspended: too many requests`` rather than as an empty result. Searches
   are therefore best made one at a time. The endpoint also omits the ``topics``
   key entirely when a query matches nothing, so a phrase with no hits yields an
   empty result rather than an error.
"""

from urllib.parse import urlencode
from datetime import datetime

from searx.result_types import EngineResults
from searx.utils import html_to_text

about = {
    "website": "https://discuss.liferay.com",
    "official_api_documentation": "https://meta.discourse.org/t/search-api/13060",
    "use_official_api": True,
    "require_api_key": False,
    "results": "JSON",
}

base_url = "https://discuss.liferay.com"
categories = ["it"]
paging = False


def request(query, params):
    query_params = {"q": query}
    params["url"] = f"{base_url}/search.json?{urlencode(query_params)}"
    return params


def response(resp) -> EngineResults:
    results = EngineResults()

    for topic in resp.json().get("topics", []):
        slug, topic_id = topic.get("slug"), topic.get("id")
        if not slug or not topic_id:
            continue
        results.add(
            results.types.LegacyResult(
                {
                    "url": f"{base_url}/t/{slug}/{topic_id}",
                    "title": topic.get("title"),
                    # the excerpt carries a trailing ellipsis and HTML
                    "content": html_to_text(topic.get("excerpt") or ""),
                    "publishedDate": _parse_date(topic.get("created_at")),
                }
            )
        )

    return results


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None
