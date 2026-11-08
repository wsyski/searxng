# SPDX-License-Identifier: AGPL-3.0-or-later
"""RDF Przegladarka (rdf-przegladarka.ms.gov.pl) — KRS financial-documents registry

The Ministry of Justice repository of financial documents filed by KRS
entities. A query is a KRS number (digits; shorter values are zero-padded,
exactly what the site's own form does) and the rows are that entity's filed
documents. The visible page is an Angular SPA whose container is empty; the
data comes from a JSON API::

    POST /services/rdf/przegladarka-dokumentow-finansowych/dokumenty/wyszukiwanie

.. attention::

   **The API takes an AES-encrypted KRS, the entity endpoint does not.**
   Captured from a real browser 2026-11-08: ``podmioty/wyszukiwanie/dane-podstawowe``
   accepts plain ``{"numerKRS": "5828"}``, but ``dokumenty/wyszukiwanie``
   demands the SPA's double AES-CBC blob as ``nrKRS`` — plaintext answers
   **422** ``Blad szyfrowania KRS``. The SPA picks a fresh random 16-digit
   key per call and wraps ``aes(krs) + "." + key`` under a static ``permKey``;
   any valid construction is accepted, so this engine uses a fixed key and the
   pure-Python AES below (no new dependency).

.. attention::

   **Incapsula gates the API for non-JS clients.** Headless Chrome is
   hard-blocked (403 "Request unsuccessful"), a headed browser passes
   silently, and a plain HTTP client is answered an interstitial
   ("Pardon Our Interruption") with status 200 — so the engine must check the
   BODY, not the status, and reports the interstitial as a captcha state
   rather than as zero results. Whether a given IP passes is Imperva's
   decision on the day; the engine is best-effort by design.

There is no deep link to a document: the SPA stays on ``/wyszukaj-podmiot``
and streams bytes from ``dokumenty/<id>/tresc``. The engine uses that
direct-download URL as the row URL (the encrypted id is percent-encoded).
Document-type *names* are resolved client-side from a cached lookup the
engine does not fetch, so rows carry the type CODE plus the reporting period.
"""

import base64
import json
import re
import typing as t
from urllib.parse import quote

from searx.exceptions import (
    SearxEngineCaptchaException,
    SearxEngineResponseException,
)
from searx.result_types import EngineResults

about = {
    "website": "https://rdf-przegladarka.ms.gov.pl",
    "official_api_documentation": "https://rdf.ms.gov.pl",
    "use_official_api": True,
    "require_api_key": False,
    "results": "JSON",
}

categories = ["finance", "finance poland"]
paging = True

base_url = "https://rdf-przegladarka.ms.gov.pl/services/rdf/przegladarka-dokumentow-finansowych"

# The SPA's static layer-2 key (extracted from main-*.js 2026-11-08:
# permKey="6a5Qm4W&MkiD=hwo"); the layer-1 key is client-random, and any
# valid value is accepted, so this engine pins one.
_PERM_KEY = b"6a5Qm4W&MkiD=hwo"
_FIXED_KRS_KEY = b"0001020304050607"

_INTERSTITIAL = ("Pardon Our Interruption", "_Incapsula_Resource", "Incapsula incident ID")

_SBOX = bytes(
    [
        0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
        0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
        0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
        0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
        0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
        0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
        0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
        0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
        0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
        0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
        0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
        0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
        0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
        0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
        0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
        0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
    ]
)


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1B) & 0xFF
    return a


def _mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _expand_key(key: bytes) -> bytes:
    out = bytearray(key)
    rcon = 1
    for i in range(4, 44):
        temp = list(out[4 * (i - 1) : 4 * i])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        for j, b in enumerate(temp):
            out.append(out[4 * (i - 4) + j] ^ b)
    return bytes(out)


def _encrypt_block(block: bytes, rk: bytes) -> bytes:
    state = list(block)  # column-major: state[r + 4c]

    def add_round_key(rnd: int) -> None:
        for i in range(16):
            state[i] ^= rk[16 * rnd + i]

    add_round_key(0)
    for rnd in range(1, 11):
        for i in range(16):
            state[i] = _SBOX[state[i]]
        # ShiftRows (column-major layout)
        state = (
            [state[0], state[5], state[10], state[15]]
            + [state[4], state[9], state[14], state[3]]
            + [state[8], state[13], state[2], state[7]]
            + [state[12], state[1], state[6], state[11]]
        )
        if rnd != 10:
            for c in range(4):
                col = state[4 * c : 4 * c + 4]
                mixed = [
                    _mul(col[0], 2) ^ _mul(col[1], 3) ^ col[2] ^ col[3],
                    col[0] ^ _mul(col[1], 2) ^ _mul(col[2], 3) ^ col[3],
                    col[1] ^ _mul(col[2], 2) ^ _mul(col[3], 3) ^ col[0],
                    _mul(col[3], 2) ^ _mul(col[0], 3) ^ col[1] ^ col[2],
                ]
                state[4 * c : 4 * c + 4] = mixed
        add_round_key(rnd)
    return bytes(state)


def _aes_cbc_encrypt(key: bytes, data: bytes) -> bytes:
    rk = _expand_key(key)
    pad = 16 - len(data) % 16
    data = data + bytes([pad]) * pad
    prev = bytes(16)
    out = bytearray()
    for off in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[off : off + 16], prev))
        prev = _encrypt_block(block, rk)
        out += prev
    return bytes(out)


def _encrypt_nrkrs(krs: str) -> str:
    """The SPA's encryptNrKrs: aes(krs) + \".\" + key, wrapped under permKey."""
    inner = base64.b64encode(_aes_cbc_encrypt(_FIXED_KRS_KEY, krs.encode())).decode()
    outer = _aes_cbc_encrypt(_PERM_KEY, f"{inner}.{_FIXED_KRS_KEY.decode()}".encode())
    return base64.b64encode(outer).decode()


def request(query, params):
    digits = re.sub(r"\D", "", query) or "0"
    body = {
        "nrKRS": _encrypt_nrkrs(digits.zfill(10)),
        "metadaneStronicowania": {
            "numerStrony": max(params.get("pageno", 1) - 1, 0),
            "rozmiarStrony": 10,
            "metadaneSortowania": [{"atrybut": "id", "kierunek": "MALEJACO"}],
        },
    }
    params["url"] = f"{base_url}/dokumenty/wyszukiwanie"
    params["data"] = json.dumps(body)
    params["headers"] = {**params.get("headers", {}), "Content-Type": "application/json"}
    params["raise_for_httperror"] = False
    return params


def response(resp) -> EngineResults:
    if resp.status_code == 403:
        raise SearxEngineCaptchaException(message="rdf: Incapsula block (403)")
    if resp.status_code == 422:
        raise SearxEngineResponseException("rdf: 422 (KRS encryption refused)")
    if resp.status_code != 200:
        raise SearxEngineResponseException(f"rdf: unexpected status {resp.status_code}")

    try:
        payload = json.loads(resp.text)
    except json.JSONDecodeError as exc:
        # The 200-status Incapsula interstitial lands here.
        if any(marker in resp.text for marker in _INTERSTITIAL):
            raise SearxEngineCaptchaException(message="rdf: Incapsula interstitial") from exc
        raise SearxEngineResponseException(f"rdf: not JSON ({resp.text[:60]!r})") from exc

    results = EngineResults()
    for row in payload.get("content", []):
        doc_id = row.get("id")
        if not doc_id:
            continue
        okres = _okres(row.get("okresSprawozdawczyPoczatek"), row.get("okresSprawozdawczyKoniec"))
        results.add(
            results.types.LegacyResult(
                {
                    "url": f"{base_url}/dokumenty/{quote(str(doc_id), safe='')}/tresc?bezPodpisu=false",
                    "title": f"Dokument {row.get('rodzaj', '?')} ({okres})" if okres else f"Dokument {row.get('rodzaj', '?')}",
                    "content": f"status: {row.get('status', '?')}",
                }
            )
        )

    return results


def _okres(start: t.Any, end: t.Any) -> str:
    if start and end:
        return f"{start} - {end}"
    return str(start or end or "")
