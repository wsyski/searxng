# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name

import typing

import searx.plugins

from searx.enginelib import Engine
from searx.engines import engines
from searx.preferences import Preferences
from searx.search.models import EngineRef
from searx.webadapter import get_search_query_from_webapp, parse_generic, validate_engineref_list

from tests import SearxTestCase

PRIVATE_ENGINE_NAME = "dummy private engine"  # from the ./settings/test_settings.yml
SEARCHQUERY = [EngineRef(PRIVATE_ENGINE_NAME, "general")]


def preferences_for(*tokens: str) -> Preferences:
    """A Preferences built over this instance's engine registry.

    ``searx.engines.engines`` is ``dict[str, Engine | ModuleType]`` - both engine
    styles coexist - while ``Preferences`` declares ``dict[str, Engine]``, and
    ``dict`` is invariant in its value type, so the plain call is a type error.
    The cast is here once rather than at each of the five call sites.
    """
    preferences = Preferences(['simple'], ['general'], typing.cast(dict[str, Engine], engines), searx.plugins.STORAGE)
    if tokens:
        preferences.parse_dict({'tokens': ','.join(tokens)})
    return preferences


class ValidateQueryCase(SearxTestCase):

    def test_without_token(self):
        preferences = preferences_for()
        valid, unknown, invalid_token = validate_engineref_list(SEARCHQUERY, preferences)
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(unknown), 0)
        self.assertEqual(len(invalid_token), 1)

    def test_with_incorrect_token(self):
        preferences_with_tokens = preferences_for('bad-token')
        valid, unknown, invalid_token = validate_engineref_list(SEARCHQUERY, preferences_with_tokens)
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(unknown), 0)
        self.assertEqual(len(invalid_token), 1)

    def test_with_correct_token(self):
        preferences_with_tokens = preferences_for('my-token')
        valid, unknown, invalid_token = validate_engineref_list(SEARCHQUERY, preferences_with_tokens)
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(unknown), 0)
        self.assertEqual(len(invalid_token), 0)


class UnknownEnginePinCase(SearxTestCase):
    """An ``engines=`` name this instance does not have is filtered out before an
    :py:obj:`EngineRef` exists for it, so :py:func:`validate_engineref_list`
    never sees it. If *every* pin is unknown the explicit list is empty and the
    **default** search runs - measured on the deployed instance as
    ``engines=mojeek news`` answering with 96 rows from three other engines. The
    response has to name what it ignored or that is indistinguishable from a
    successful pinned search.
    """

    def _parse(self, form):
        return parse_generic(preferences_for(), form, [])

    def test_unknown_pin_is_reported(self):
        engineref_list, unknown, _ = self._parse({'engines': 'no such engine'})
        self.assertEqual(unknown, ['no such engine'])
        # the fallback itself is upstream behaviour and is left alone
        self.assertNotEqual(engineref_list, [])

    def test_known_pin_reports_nothing(self):
        _, unknown, _ = self._parse({'engines': 'dummy engine'})
        self.assertEqual(unknown, [])

    def test_mixed_pins_report_only_the_unknown_one(self):
        engineref_list, unknown, _ = self._parse({'engines': 'dummy engine,no such engine'})
        self.assertEqual(unknown, ['no such engine'])
        self.assertEqual([ref.name for ref in engineref_list], ['dummy engine'])

    def test_empty_name_is_not_an_engine(self):
        _, unknown, _ = self._parse({'engines': 'dummy engine,'})
        self.assertEqual(unknown, [])

    def test_search_query_carries_the_unknown_names(self):
        search_query, _, _, _, _ = get_search_query_from_webapp(
            preferences_for(), {'q': 'kghm', 'engines': 'no such engine'}
        )
        self.assertEqual(search_query.unknown_engines, ['no such engine'])


class UnknownCategoryCase(SearxTestCase):
    """A ``categories=`` name this instance does not have is dropped in
    :py:func:`searx.webadapter.parse_category_form`, which leaves the category
    list empty - and an empty list means the **default** search. Measured on the
    deployed instance: ``categories=finance-polnd`` answered 36 rows from
    mwmbl / duckduckgo web / yahoo, with an empty ``unknown_engines`` and
    nothing anywhere saying the category never ran. A caller cannot tell that
    from the category answering with those rows, which is the whole bug.
    """

    def _parse(self, form):
        return parse_generic(preferences_for(), form, [])

    def test_unknown_category_is_reported(self):
        engineref_list, _, unknown = self._parse({'categories': 'finance-polnd'})
        self.assertEqual(unknown, ['finance-polnd'])
        # the fallback itself is upstream behaviour and is left alone
        self.assertNotEqual(engineref_list, [])

    def test_known_category_reports_nothing(self):
        _, _, unknown = self._parse({'categories': 'general'})
        self.assertEqual(unknown, [])

    def test_mixed_categories_report_only_the_unknown_one(self):
        _, _, unknown = self._parse({'categories': 'general,finance-polnd'})
        self.assertEqual(unknown, ['finance-polnd'])

    def test_empty_name_is_not_a_category(self):
        _, _, unknown = self._parse({'categories': 'general,'})
        self.assertEqual(unknown, [])

    def test_category_form_field_is_reported_too(self):
        _, _, unknown = self._parse({'category_finance-polnd': 'on'})
        self.assertEqual(unknown, ['finance-polnd'])

    def test_switching_an_unknown_category_off_is_not_a_request_for_it(self):
        _, _, unknown = self._parse({'category_finance-polnd': 'off'})
        self.assertEqual(unknown, [])

    def test_search_query_carries_the_unknown_names(self):
        search_query, _, _, _, _ = get_search_query_from_webapp(
            preferences_for(), {'q': 'kghm', 'categories': 'finance-polnd'}
        )
        self.assertEqual(search_query.unknown_categories, ['finance-polnd'])
