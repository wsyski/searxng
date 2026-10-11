# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name

"""Tests for the fork-local patch to searx/engines/github.py.

Only one thing changed upstream: `request()` now adds an Authorization header
when GITHUB_PERSONAL_ACCESS_TOKEN is set. The tests cover both branches, because
the failure that matters is silent - the instance simply keeps answering at the
unauthenticated rate until SearXNG suspends the engine for 180 s and reports
it as "access denied".

The token is read from the environment on every call rather than cached, so a
test can set and unset it around a single invocation.
"""

import os
from unittest import mock

import searx.engines
from tests import SearxTestCase


class TestGithubEngineAuth(SearxTestCase):

    TEST_SETTINGS = "test_github.yml"

    def setUp(self):
        super().setUp()
        self.engine = searx.engines.engines["github"]

    def _request(self, token=None):
        """Call request() with the token set or provably unset.

        The no-token case pops the variable explicitly rather than relying on it
        being absent, so an ambient value in the shell cannot decide it.
        """
        params = {"headers": {}}
        env = {} if token is None else {"GITHUB_PERSONAL_ACCESS_TOKEN": token}
        os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
        try:
            with mock.patch.dict(os.environ, env, clear=False):
                self.engine.request("react hooks", params)
        finally:
            os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
        return params

    def test_no_token_means_no_authorization_header(self):
        """The unauthenticated path must stay the default: the token is optional
        and its absence must not raise or add a broken header."""
        params = self._request()
        self.assertNotIn("Authorization", params["headers"])

    def test_a_blank_token_is_treated_as_absent(self):
        """An empty or whitespace value would otherwise produce `Bearer ` -
        a header GitHub rejects, which would look like a revoked token rather
        than an unset one."""
        for blank in ("", "   ", "\n"):
            params = self._request(blank)
            self.assertNotIn("Authorization", params["headers"], f"blank {blank!r} sent a header")

    def test_a_token_is_sent_as_a_bearer_header(self):
        params = self._request("ghp_example")
        self.assertEqual(params["headers"]["Authorization"], "Bearer ghp_example")

    def test_the_token_is_stripped_before_use(self):
        """A token pasted with a trailing newline - the usual way one lands in a
        dotenv - would otherwise be sent verbatim and rejected as malformed."""
        params = self._request("ghp_example\n")
        self.assertEqual(params["headers"]["Authorization"], "Bearer ghp_example")

    def test_the_accept_header_survives_the_patch(self):
        """The patch adds a header; it must not displace the one GitHub needs to
        return the text-match fields this engine parses."""
        params = self._request("ghp_example")
        self.assertEqual(params["headers"]["Accept"], self.engine.accept_header)

    def test_the_search_url_is_unchanged(self):
        params = self._request("ghp_example")
        self.assertIn("api.github.com/search/repositories", params["url"])
        self.assertIn("react+hooks", params["url"])

    def test_it_still_uses_the_official_api(self):
        """A token only helps because this engine calls the API. If a future
        change moved it to scraping github.com, the header would do nothing."""
        self.assertTrue(self.engine.about.use_official_api)
        self.assertEqual(self.engine.about.results, "JSON")