"""Tests for the update-visibility switch."""
from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.update_manager.const import DOMAIN, STORAGE_KEY_UPDATES

_HIDDEN_BY = er.RegistryEntryHider.INTEGRATION
SWITCH = "switch.toon_updates_in_instellingen"


def _make_update_entity(registry: er.EntityRegistry, uid: str, **kwargs) -> str:
    """Create an ``update.*`` entity in the registry and return its entity_id."""
    entry = registry.async_get_or_create("update", "demo", uid, **kwargs)
    return entry.entity_id


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


async def test_default_state_on(hass):
    """Without restored state the switch defaults to on and hides nothing."""
    registry = er.async_get(hass)
    ent = _make_update_entity(registry, "u1")

    await _setup(hass)

    assert hass.states.get(SWITCH).state == STATE_ON
    assert registry.async_get(ent).hidden_by is None


async def test_turn_off_hides_only_visible_updates(hass, hass_storage):
    """Turning off hides visible update entities but never externally hidden ones."""
    registry = er.async_get(hass)
    visible = _make_update_entity(registry, "visible")
    external = _make_update_entity(
        registry, "external", hidden_by=er.RegistryEntryHider.USER
    )

    await _setup(hass)
    await _call(hass, "turn_off")

    assert hass.states.get(SWITCH).state == STATE_OFF
    assert registry.async_get(visible).hidden_by == _HIDDEN_BY
    # Externally hidden entity keeps its original hidden_by value.
    assert registry.async_get(external).hidden_by == er.RegistryEntryHider.USER

    stored = hass_storage[STORAGE_KEY_UPDATES]["data"]
    assert stored["hidden_entity_ids"] == [visible]


async def test_turn_on_restores_only_hidden_by_us(hass):
    """Turning back on un-hides exactly the entities the switch hid."""
    registry = er.async_get(hass)
    ours = _make_update_entity(registry, "ours")
    external = _make_update_entity(
        registry, "external", hidden_by=er.RegistryEntryHider.USER
    )

    await _setup(hass)
    await _call(hass, "turn_off")
    await _call(hass, "turn_on")

    assert hass.states.get(SWITCH).state == STATE_ON
    assert registry.async_get(ours).hidden_by is None
    assert registry.async_get(external).hidden_by == er.RegistryEntryHider.USER


async def test_turn_on_drops_removed_entities(hass, hass_storage):
    """A tracked entity that no longer exists is silently dropped on turn-on."""
    registry = er.async_get(hass)
    gone = _make_update_entity(registry, "gone")

    await _setup(hass)
    await _call(hass, "turn_off")

    registry.async_remove(gone)
    await _call(hass, "turn_on")

    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass_storage[STORAGE_KEY_UPDATES]["data"]["hidden_entity_ids"] == []


async def test_restore_off_hides_existing_updates(hass):
    """A restored 'off' state hides pre-existing update entities during setup."""
    mock_restore_cache(hass, (State(SWITCH, STATE_OFF),))
    registry = er.async_get(hass)
    ent = _make_update_entity(registry, "restored")

    await _setup(hass)

    assert hass.states.get(SWITCH).state == STATE_OFF
    assert registry.async_get(ent).hidden_by == _HIDDEN_BY


async def test_new_update_entity_hidden_while_off(hass):
    """A newly registered update entity is auto-hidden while the switch is off."""
    registry = er.async_get(hass)
    await _setup(hass)
    await _call(hass, "turn_off")

    new_ent = _make_update_entity(registry, "new")
    await hass.async_block_till_done()

    assert registry.async_get(new_ent).hidden_by == _HIDDEN_BY


async def test_new_update_entity_not_hidden_while_on(hass):
    """A newly registered update entity stays visible while the switch is on."""
    registry = er.async_get(hass)
    await _setup(hass)

    new_ent = _make_update_entity(registry, "new")
    await hass.async_block_till_done()

    assert registry.async_get(new_ent).hidden_by is None


async def test_already_hidden_new_entity_untouched_while_off(hass):
    """A newly created update entity already hidden externally is left alone."""
    registry = er.async_get(hass)
    await _setup(hass)
    await _call(hass, "turn_off")

    new_ent = _make_update_entity(
        registry, "prehidden", hidden_by=er.RegistryEntryHider.USER
    )
    await hass.async_block_till_done()

    assert registry.async_get(new_ent).hidden_by == er.RegistryEntryHider.USER


async def test_non_update_entity_ignored_while_off(hass):
    """Registry changes for non-update entities are ignored by the update switch."""
    registry = er.async_get(hass)
    await _setup(hass)
    await _call(hass, "turn_off")

    other = registry.async_get_or_create("sensor", "demo", "s1").entity_id
    await hass.async_block_till_done()

    assert registry.async_get(other).hidden_by is None
