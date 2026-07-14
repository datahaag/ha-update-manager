"""Tests for setup / unload / reload of the Update Manager integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.update_manager.const import DOMAIN


async def _add_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_entry(hass):
    """Setting up an entry stores per-entry data and loads the switch platform."""
    entry = await _add_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][entry.entry_id] == {}
    assert hass.states.get("switch.toon_updates_in_instellingen") is not None
    assert hass.states.get("switch.toon_reparaties_in_instellingen") is not None


async def test_unload_entry(hass):
    """Unloading an entry removes the per-entry data."""
    entry = await _add_entry(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_reload_on_options_update(hass):
    """Updating the entry triggers the reload listener and keeps it loaded."""
    entry = await _add_entry(hass)

    hass.config_entries.async_update_entry(entry, data={"changed": True})
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id in hass.data[DOMAIN]
