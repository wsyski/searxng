# SPDX-License-Identifier: AGPL-3.0-or-later
"""Github (IT)"""

import os
from urllib.parse import urlencode

from dateutil import parser

# about
about = {
    "website": 'https://github.com/',
    "wikidata_id": 'Q364',
    "official_api_documentation": 'https://developer.github.com/v3/',
    "use_official_api": True,
    "require_api_key": False,
    "results": 'JSON',
}

# engine dependent config
categories = ['it', 'repos']

# search-url
search_url = 'https://api.github.com/search/repositories?sort=stars&order=desc&{query}'
accept_header = 'application/vnd.github.preview.text-match+json'


def request(query, params):

    params['url'] = search_url.format(query=urlencode({'q': query}))
    params['headers']['Accept'] = accept_header

    # Authenticated search lifts GitHub's ceiling from 10 to 30 requests a minute.
    # Unauthenticated, roughly twenty queries in three minutes is enough to make
    # SearXNG suspend this engine for 180 s, reporting it as "access denied" -
    # which reads as a block rather than a throttle. See the fork's searxng
    # skill, references/categories.md, "A suspension is not a block".
    #
    # Read from the environment, never from settings.yml: this instance has no
    # authentication and no limiter, and settings.yml is tracked in git. The
    # token belongs in the gitignored container/.env.prod, which compose passes
    # in through env_file. Searching public repositories needs no scopes at all,
    # so a token with none is sufficient.
    token = os.environ.get('GITHUB_PERSONAL_ACCESS_TOKEN', '').strip()
    if token:
        params['headers']['Authorization'] = f'Bearer {token}'

    return params


def response(resp):
    results = []

    for item in resp.json().get('items', []):
        content = [item.get(i) for i in ['language', 'description'] if item.get(i)]

        # license can be None
        lic = item.get('license') or {}
        lic_url = None
        if lic.get('spdx_id'):
            lic_url = f"https://spdx.org/licenses/{lic.get('spdx_id')}.html"

        results.append(
            {
                'template': 'packages.html',
                'url': item.get('html_url'),
                'title': item.get('full_name'),
                'content': ' / '.join(content),
                'thumbnail': item.get('owner', {}).get('avatar_url'),
                'package_name': item.get('name'),
                # 'version': item.get('updated_at'),
                'maintainer': item.get('owner', {}).get('login'),
                'publishedDate': parser.parse(item.get("updated_at") or item.get("created_at")),
                'tags': item.get('topics', []),
                'popularity': item.get('stargazers_count'),
                'license_name': lic.get('name'),
                'license_url': lic_url,
                'homepage': item.get('homepage'),
                'source_code_url': item.get('clone_url'),
            }
        )

    return results
