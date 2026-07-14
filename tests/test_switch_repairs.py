"""Tests for the repair-visibility switch.

The repairs issue registry lives at an import path that is not importable on
every Home Assistant version, so the switch loads it lazily through
``_get_issue_registry``.  These tests patch that helper with a light-weight fake
registry so the switch logic can be exercised deterministically.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.update_manager.const import DOMAIN, STORAGE_KEY_REPAIRS

SWITCH = "switch.toon_reparaties_in_instellingen"
_PATCH_TARGET = "custom_components.update_manager.switch._get_issue_registry"


class FakeIssue:
    """Minimal stand-in for a repairs ``IssueEntry``."""

    def __init__(self, ignored: bool = False, dismissed_version=None) -> None:
        self.ignored = ignored
        self.dismissed_version = dismissed_version


class FakeIssueRegistry:
    """Minimal stand-in for the repairs issue registry."""

    def __init__(self) -> None:
        self.issues: dict[tuple[str, str], FakeIssue] = {}

    def add(self, domain: str, issue_id: str, issue: FakeIssue) -> None:
        self.issues[(domain, issue_id)] = issue

    def async_ignore(self, domain: str, issue_id: str, ignore: bool) -> None:
        self.issues[(domain, issue_id)].ignored = ignore


@pytest.fixture
def issue_registry() -> FakeIssueRegistry:
    return FakeIssueRegistry()


async def _setup(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _call(hass, service: str) -> None:
    await hass.services.async_call(
        "switch", service, {"entity_id": SWITCH}, blocking=True
    )
    await hass.async_block_till_done()


async def test_turn_off_ignores_active_issues(hass, issue_registry, hass_storage):
    """Turning off ignores active issues but leaves ignored/dismissed ones alone."""
    active = FakeIssue()
    already_ignored = FakeIssue(ignored=True)
    dismissed = FakeIssue(dismissed_version="1.2.3")
    issue_registry.add("hue", "bulb", active)
    issue_registry.add("cast", "old", already_ignored)
    issue_registry.add("zwave", "stick", dismissed)

    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)
        await _call(hass, "turn_off")

    assert hass.states.get(SWITCH).state == STATE_OFF
    assert active.ignored is True
    assert dismissed.ignored is False  # dismissed issues are skipped

    stored = hass_storage[STORAGE_KEY_REPAIRS]["data"]["ignored_issue_ids"]
    assert stored == [["hue", "bulb"]]


async def test_turn_on_unignores_only_ours(hass, issue_registry):
    """Turning on restores only issues the switch ignored itself."""
    ours = FakeIssue()
    other = FakeIssue(ignored=True)
    issue_registry.add("hue", "bulb", ours)
    issue_registry.add("cast", "old", other)

    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)
        await _call(hass, "turn_off")
        await _call(hass, "turn_on")

    assert hass.states.get(SWITCH).state == STATE_ON
    assert ours.ignored is False
    assert other.ignored is True  # untouched


async def test_turn_on_drops_resolved_issue(hass, issue_registry, hass_storage):
    """An ignored issue that disappears is dropped from tracking on turn-on."""
    issue = FakeIssue()
    issue_registry.add("hue", "bulb", issue)

    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)
        await _call(hass, "turn_off")

        del issue_registry.issues[("hue", "bulb")]
        await _call(hass, "turn_on")

    assert hass_storage[STORAGE_KEY_REPAIRS]["data"]["ignored_issue_ids"] == []


async def test_restore_off_ignores_existing_issues(hass, issue_registry):
    """A restored 'off' state ignores pre-existing issues during setup."""
    mock_restore_cache(hass, (State(SWITCH, STATE_OFF),))
    issue = FakeIssue()
    issue_registry.add("hue", "bulb", issue)

    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)

    assert hass.states.get(SWITCH).state == STATE_OFF
    assert issue.ignored is True


async def test_restore_tracked_ids_from_store(hass, issue_registry, hass_storage):
    """Previously-ignored ids are loaded from storage and un-ignored on turn-on."""
    hass_storage[STORAGE_KEY_REPAIRS] = {
        "version": 1,
        "data": {"ignored_issue_ids": [["hue", "bulb"], ["bad"]]},
    }
    issue = FakeIssue(ignored=True)
    issue_registry.add("hue", "bulb", issue)

    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)  # starts 'on' -> restores tracked ids
        await hass.async_block_till_done()

    # The malformed 2-tuple was filtered out; the valid one was un-ignored.
    assert issue.ignored is False


async def test_new_issue_ignored_while_off(hass, issue_registry):
    """A newly created repair issue is auto-ignored while the switch is off."""
    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)
        await _call(hass, "turn_off")

        issue = FakeIssue()
        issue_registry.add("hue", "new", issue)
        hass.bus.async_fire(
            "repairs_issue_registry_updated",
            {"action": "create", "domain": "hue", "issue_id": "new"},
        )
        await hass.async_block_till_done()

    assert issue.ignored is True


async def test_new_issue_not_ignored_while_on(hass, issue_registry):
    """A newly created repair issue stays visible while the switch is on."""
    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)

        issue = FakeIssue()
        issue_registry.add("hue", "new", issue)
        hass.bus.async_fire(
            "repairs_issue_registry_updated",
            {"action": "create", "domain": "hue", "issue_id": "new"},
        )
        await hass.async_block_till_done()

    assert issue.ignored is False


async def test_new_issue_event_guards(hass, issue_registry):
    """Malformed / non-create events do not ignore anything while off."""
    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)
        await _call(hass, "turn_off")

        # Wrong action.
        issue = FakeIssue()
        issue_registry.add("hue", "x", issue)
        hass.bus.async_fire(
            "repairs_issue_registry_updated",
            {"action": "remove", "domain": "hue", "issue_id": "x"},
        )
        # Missing identifiers.
        hass.bus.async_fire(
            "repairs_issue_registry_updated",
            {"action": "create", "domain": "", "issue_id": ""},
        )
        # Unknown issue id -> handler returns without touching the registry.
        hass.bus.async_fire(
            "repairs_issue_registry_updated",
            {"action": "create", "domain": "hue", "issue_id": "missing"},
        )
        await hass.async_block_till_done()

    assert issue.ignored is False


async def test_no_issue_registry_is_noop(hass):
    """When the issue registry is unavailable the switch degrades gracefully."""
    with patch(_PATCH_TARGET, return_value=None):
        await _setup(hass)
        await _call(hass, "turn_off")

    assert hass.states.get(SWITCH).state == STATE_OFF


async def test_new_issue_noop_without_registry(hass, issue_registry):
    """The new-issue handler is a no-op if the registry becomes unavailable."""
    with patch(_PATCH_TARGET, return_value=issue_registry):
        await _setup(hass)
        await _call(hass, "turn_off")

    issue = FakeIssue()
    issue_registry.add("hue", "late", issue)
    with patch(_PATCH_TARGET, return_value=None):
        hass.bus.async_fire(
            "repairs_issue_registry_updated",
            {"action": "create", "domain": "hue", "issue_id": "late"},
        )
        await hass.async_block_till_done()

    assert issue.ignored is False


async def test_get_issue_registry_returns_registry_when_importable(hass):
    """``_get_issue_registry`` returns the registry when the module imports."""
    from custom_components.update_manager import switch as switch_module

    sentinel = object()
    fake_module = types.ModuleType(
        "homeassistant.components.repairs.issue_registry"
    )
    fake_module.async_get = lambda _hass: sentinel

    with patch.dict(
        sys.modules,
        {"homeassistant.components.repairs.issue_registry": fake_module},
    ):
        assert switch_module._get_issue_registry(hass) is sentinel


async def test_get_issue_registry_returns_none_when_missing(hass):
    """``_get_issue_registry`` returns None when the module is unavailable."""
    from custom_components.update_manager import switch as switch_module

    with patch.dict(
        sys.modules,
        {"homeassistant.components.repairs.issue_registry": None},
    ):
        assert switch_module._get_issue_registry(hass) is None
