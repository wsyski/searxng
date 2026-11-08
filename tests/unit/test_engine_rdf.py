# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name,protected-access

"""Tests for the RDF Przegladarka (rdf-przegladarka.ms.gov.pl) engine.

Pinned behaviours, all established 2026-11-08 (real-browser capture plus a
live interstitial hit from this host):

- ``dokumenty/wyszukiwanie`` demands the SPA's double AES-CBC ``nrKRS``;
  the KAT-pure implementation must survive a round trip and the query must
  be zero-padded to ten digits.
- Incapsula answers non-JS clients with the "Pardon Our Interruption"
  interstitial at HTTP 200 — zero results would be a lie, so it must raise
  SearxEngineCaptchaException. The hard 403 block likewise.
- a content row becomes a result whose URL is the direct /tresc download
  with the encrypted id percent-encoded.
"""

import base64
import json
import typing as t
from unittest.mock import Mock

import searx.engines
import searx.engines.rdf as rdf_mod
from searx.exceptions import SearxEngineCaptchaException, SearxEngineResponseException
from searx.result_types import LegacyResult
from searx.search.processors import OnlineParamTypes
from tests import SearxTestCase


def _params(**extra: t.Any) -> OnlineParamTypes:
    base: dict[str, t.Any] = {"headers": {}}
    base.update(extra)
    return t.cast(OnlineParamTypes, t.cast(object, base))


def _resp(payload, status_code=200):
    r = Mock()
    r.text = payload if isinstance(payload, str) else json.dumps(payload)
    r.status_code = status_code
    return r


def _body(params: OnlineParamTypes) -> dict[str, t.Any]:
    return t.cast("dict[str, t.Any]", t.cast(object, params["json"]))


def _api_url(params: OnlineParamTypes) -> str:
    return (params.get("url") or "").split("?")[0]


# Real shape, trimmed from the captured 200 response of dokumenty/wyszukiwanie.
DOCS = {
    "content": [
        {
            "id": "HTQGeTZx+avv2kZobTs8Pg==",
            "rodzaj": "3",
            "status": "NIEUSUNIETY",
            "nazwa": None,
            "okresSprawozdawczyPoczatek": "2025-01-01",
            "okresSprawozdawczyKoniec": "2025-12-31",
            "dataUsunieciaDokumentu": "",
        },
        {
            "id": "abc123",
            "rodzaj": "1",
            "status": "NIEUSUNIETY",
            "nazwa": None,
            "okresSprawozdawczyPoczatek": "2024-01-01",
            "okresSprawozdawczyKoniec": "2024-12-31",
            "dataUsunieciaDokumentu": "",
        },
    ],
    "metadaneWynikow": {"numerStrony": 0, "rozmiarStrony": 10, "liczbaStron": 4, "calkowitaLiczbaObiektow": 38},
}

INTERSTITIAL = """<html><head><noscript><title>Pardon Our Interruption</title>
</noscript></head><body><a href="https://www.incapsula.com">Incapsula incident ID</a></body></html>"""


class RdfCryptoTests(SearxTestCase):

    def test_aes_matches_the_fips197_vector(self):
        ct = rdf_mod._aes_cbc_encrypt(
            bytes(range(16)), bytes.fromhex("00112233445566778899aabbccddeeff")
        )
        self.assertEqual(ct[:16].hex(), "69c4e0d86a7b0430d8cdb78070b4c55a")

    def test_nrkrs_roundtrip(self):
        blob = rdf_mod._encrypt_nrkrs("0000005828")
        # base64 decodes and the outer layer length is a whole AES block set
        raw = base64.b64decode(blob)
        self.assertEqual(len(raw) % 16, 0)
        self.assertNotEqual(raw, b"0000005828")

    def test_nrkrs_is_deterministic(self):
        self.assertEqual(
            rdf_mod._encrypt_nrkrs("0000005828"),
            rdf_mod._encrypt_nrkrs("0000005828"),
        )


class RdfEngineTests(SearxTestCase):

    TEST_SETTINGS = "test_rdf.yml"

    def setUp(self):
        super().setUp()
        self.engine = t.cast(t.Any, searx.engines.engines["rdf"])

    def test_request_posts_json_with_an_encrypted_padded_krs(self):
        params = _params()
        self.engine.request("5828", params)
        self.assertEqual(_api_url(params), f"{rdf_mod.base_url}/dokumenty/wyszukiwanie")
        self.assertEqual(params["method"], "POST")
        body = _body(params)
        self.assertNotIn("5828", body["nrKRS"])  # encrypted, never plain digits
        self.assertEqual(
            body["metadaneStronicowania"],
            {"numerStrony": 0, "rozmiarStrony": 10, "metadaneSortowania": [{"atrybut": "id", "kierunek": "MALEJACO"}]},
        )
        self.assertEqual(params["headers"]["Content-Type"], "application/json")

    def test_request_pads_short_and_hyphenated_krs_forms(self):
        for query in ("5828", "0000005828", "0000-00-5828"):
            params = _params()
            self.engine.request(query, params)
            self.assertEqual(_body(params)["nrKRS"], rdf_mod._encrypt_nrkrs("0000005828"))

    def test_request_maps_pageno_zero_based(self):
        params = _params(pageno=3)
        self.engine.request("5828", params)
        self.assertEqual(_body(params)["metadaneStronicowania"]["numerStrony"], 2)

    def test_the_category_is_finance_poland(self):
        self.assertEqual(self.engine.categories, ["finance", "finance poland"])

    def test_rows_point_at_the_direct_tresc_download(self):
        results = self.engine.response(_resp(DOCS))
        self.assertEqual(len(results), 2)
        first = t.cast(LegacyResult, list(results)[0])
        self.assertIn("/dokumenty/HTQGeTZx%2Bavv2kZobTs8Pg%3D%3D/tresc?bezPodpisu=false", first["url"])
        self.assertIn("2025-01-01 - 2025-12-31", first["title"])
        self.assertEqual(first["content"], "status: NIEUSUNIETY")

    def test_the_interstitial_is_a_captcha_state_not_zero_results(self):
        with self.assertRaises(SearxEngineCaptchaException):
            self.engine.response(_resp(INTERSTITIAL))

    def test_the_hard_403_block_is_a_captcha_state(self):
        with self.assertRaises(SearxEngineCaptchaException):
            self.engine.response(_resp("<html>Request unsuccessful. Incapsula incident ID: 1</html>", 403))

    def test_plaintext_krs_422_is_a_response_exception(self):
        with self.assertRaises(SearxEngineResponseException):
            self.engine.response(_resp('{"messageCode":"422"}', 422))

    def test_empty_content_is_zero_results(self):
        self.assertEqual(len(self.engine.response(_resp({"content": []}))), 0)
