"""Switch platform for Update Manager.

Two global switches:

1. UpdateVisibilitySwitch  – controls the Settings badge for *updates*
   ON  → update entities visible in Settings (default HA behaviour)
   OFF → update entities hidden from Settings badge; still on Updates page

2. RepairVisibilitySwitch  – controls the Settings badge for *repairs*
   ON  → repair issues visible in Settings (default HA behaviour)
   OFF → repair issues ignored (suppressed from Settings badge)
          When turned back ON the issues are un-ignored automatically.

Only state managed by THIS integration is ever touched; externally
hidden/ignored items are left untouched.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import storage
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STORAGE_KEY_REPAIRS, STORAGE_KEY_UPDATES, STORAGE_VERSION
from .entity import VisibilitySwitchEntity

_LOGGER = logging.getLogger(__name__)

# HA sentinel used in entity_registry hidden_by field
_HIDDEN_BY = er.RegistryEntryHider.INTEGRATION


# ---------------------------------------------------------------------------
# Platform entry point
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up both visibility switches."""
    update_store = storage.Store(hass, STORAGE_VERSION, STORAGE_KEY_UPDATES)
    repair_store = storage.Store(hass, STORAGE_VERSION, STORAGE_KEY_REPAIRS)

    async_add_entities(
        [
            UpdateVisibilitySwitch(hass, update_store),
            RepairVisibilitySwitch(hass, repair_store),
        ],
        update_before_add=True,
    )


# ---------------------------------------------------------------------------
# Helper – repairs issue registry
# ---------------------------------------------------------------------------

def _get_issue_registry(hass: HomeAssistant) -> Any | None:
    """Return the repairs issue registry, or None if the component is not loaded."""
    try:
        from homeassistant.components.repairs.issue_registry import (
            async_get as async_get_issue_registry,
        )
        return async_get_issue_registry(hass)
    except ImportError:
        _LOGGER.warning("homeassistant.components.repairs not available")
        return None


# ---------------------------------------------------------------------------
# Switch 1 – Updates
# ---------------------------------------------------------------------------

class UpdateVisibilitySwitch(VisibilitySwitchEntity):
    """Global switch: show/hide update entities in the Settings badge.

    Tracks which entity_ids it hides so it only restores exactly those
    on turn-on; externally hidden entities are never touched.
    """

    _attr_name = "Toon updates in Instellingen"
    _attr_icon = "mdi:package-up"
    _registry_event = er.EVENT_ENTITY_REGISTRY_UPDATED

    def __init__(
        self,
        hass: HomeAssistant,
        store: storage.Store,
    ) -> None:
        super().__init__(hass, store, f"{DOMAIN}_show_updates_in_settings")
        self._hidden_by_us: set[str] = set()

    def _restore_managed_items(self, stored: object | None) -> None:
        if isinstance(stored, dict) and isinstance(
            stored.get("hidden_entity_ids"), list
        ):
            self._hidden_by_us = {
                entity_id
                for entity_id in stored["hidden_entity_ids"]
                if isinstance(entity_id, str) and entity_id.startswith("update.")
            }

    async def _async_sync_visibility(self) -> None:
        registry = er.async_get(self.hass)

        if self._is_on:
            for entity_id in list(self._hidden_by_us):
                reg_entry = registry.async_get(entity_id)
                if reg_entry is None:
                    self._hidden_by_us.discard(entity_id)
                    continue
                if reg_entry.domain == "update" and reg_entry.hidden_by == _HIDDEN_BY:
                    try:
                        registry.async_update_entity(entity_id, hidden_by=None)
                    except Exception:  # noqa: BLE001 - keep syncing the rest
                        _LOGGER.exception(
                            "Failed to un-hide update entity %s; will retry later",
                            entity_id,
                        )
                        continue
                    _LOGGER.debug("Un-hiding update entity: %s", entity_id)
                self._hidden_by_us.discard(entity_id)
        else:
            for reg_entry in registry.entities.values():
                if reg_entry.domain == "update" and reg_entry.hidden_by is None:
                    try:
                        registry.async_update_entity(
                            reg_entry.entity_id, hidden_by=_HIDDEN_BY
                        )
                    except Exception:  # noqa: BLE001 - keep syncing the rest
                        _LOGGER.exception(
                            "Failed to hide update entity %s", reg_entry.entity_id
                        )
                        continue
                    self._hidden_by_us.add(reg_entry.entity_id)
                    _LOGGER.debug("Hiding update entity: %s", reg_entry.entity_id)

        await self._async_persist_managed_items()

    def _managed_items_storage_data(self) -> dict[str, object]:
        return {"hidden_entity_ids": list(self._hidden_by_us)}

    @callback
    def _handle_registry_change(self, event: Event) -> None:
        if event.data.get("action") != "create":
            return
        entity_id = event.data.get("entity_id")
        if (
            not isinstance(entity_id, str)
            or not entity_id.startswith("update.")
            or self._is_on
        ):
            return

        registry = er.async_get(self.hass)
        reg_entry = registry.async_get(entity_id)
        if reg_entry is None or reg_entry.hidden_by is not None:
            return

        try:
            registry.async_update_entity(entity_id, hidden_by=_HIDDEN_BY)
        except Exception:  # noqa: BLE001 - don't propagate into the event bus
            _LOGGER.exception(
                "Failed to hide newly registered update entity %s", entity_id
            )
            return
        self._hidden_by_us.add(entity_id)
        _LOGGER.debug("Hiding newly registered update entity: %s", entity_id)
        self.hass.async_create_task(self._async_persist_managed_items())


# ---------------------------------------------------------------------------
# Switch 2 – Repairs
# ---------------------------------------------------------------------------

class RepairVisibilitySwitch(VisibilitySwitchEntity):
    """Global switch: show/hide repair issues in the Settings badge.

    When OFF, all active (non-ignored) repair issues are marked as ignored,
    which removes the Settings badge.  The Updates page equivalent for repairs
    (Settings → Repairs, /config/repairs) still shows all issues including
    ignored ones, so users can always find and act on them.

    Tracks which (domain, issue_id) tuples it ignored so that on turn-on it
    restores only those; issues already ignored by something else are untouched.
    """

    _attr_name = "Toon reparaties in Instellingen"
    _attr_icon = "mdi:wrench-clock"
    _registry_event = "repairs_issue_registry_updated"

    def __init__(
        self,
        hass: HomeAssistant,
        store: storage.Store,
    ) -> None:
        super().__init__(hass, store, f"{DOMAIN}_show_repairs_in_settings")
        self._ignored_by_us: set[tuple[str, str]] = set()

    def _restore_managed_items(self, stored: object | None) -> None:
        if isinstance(stored, dict) and isinstance(
            stored.get("ignored_issue_ids"), list
        ):
            self._ignored_by_us = {
                (item[0], item[1])
                for item in stored["ignored_issue_ids"]
                if (
                    isinstance(item, (list, tuple))
                    and len(item) == 2
                    and isinstance(item[0], str)
                    and bool(item[0])
                    and isinstance(item[1], str)
                    and bool(item[1])
                )
            }

    async def _async_sync_visibility(self) -> None:
        issue_registry = _get_issue_registry(self.hass)
        if issue_registry is None:
            return

        if self._is_on:
            # Un-ignore only the issues we previously ignored
            for domain, issue_id in list(self._ignored_by_us):
                issue_key = (domain, issue_id)
                issue = issue_registry.issues.get(issue_key)
                if issue is None:
                    # Issue resolved itself; drop from tracking
                    self._ignored_by_us.discard(issue_key)
                    continue
                if issue.ignored:
                    try:
                        issue_registry.async_ignore(domain, issue_id, False)
                    except Exception:  # noqa: BLE001 - keep syncing the rest
                        _LOGGER.exception(
                            "Failed to un-ignore repair issue %s/%s; will retry later",
                            domain,
                            issue_id,
                        )
                        continue
                    _LOGGER.debug("Un-ignoring repair issue: %s/%s", domain, issue_id)
                self._ignored_by_us.discard(issue_key)
        else:
            # Ignore all currently active (non-ignored) issues
            for (domain, issue_id), issue in issue_registry.issues.items():
                if not issue.ignored and not issue.dismissed_version:
                    try:
                        issue_registry.async_ignore(domain, issue_id, True)
                    except Exception:  # noqa: BLE001 - keep syncing the rest
                        _LOGGER.exception(
                            "Failed to ignore repair issue %s/%s", domain, issue_id
                        )
                        continue
                    self._ignored_by_us.add((domain, issue_id))
                    _LOGGER.debug("Ignoring repair issue: %s/%s", domain, issue_id)

        await self._async_persist_managed_items()

    def _managed_items_storage_data(self) -> dict[str, object]:
        return {
            "ignored_issue_ids": [list(item) for item in self._ignored_by_us]
        }

    @callback
    def _handle_registry_change(self, event: Event) -> None:
        """Hide a newly created repair issue if the switch is OFF."""
        if self._is_on:
            return
        if event.data.get("action") != "create":
            return

        domain = event.data.get("domain")
        issue_id = event.data.get("issue_id")
        if (
            not isinstance(domain, str)
            or not domain
            or not isinstance(issue_id, str)
            or not issue_id
        ):
            return

        issue_registry = _get_issue_registry(self.hass)
        if issue_registry is None:
            return

        issue = issue_registry.issues.get((domain, issue_id))
        if issue is None or issue.ignored:
            return

        try:
            issue_registry.async_ignore(domain, issue_id, True)
        except Exception:  # noqa: BLE001 - don't propagate into the event bus
            _LOGGER.exception(
                "Failed to ignore newly created repair issue %s/%s", domain, issue_id
            )
            return
        self._ignored_by_us.add((domain, issue_id))
        _LOGGER.debug("Ignoring newly created repair issue: %s/%s", domain, issue_id)
        self.hass.async_create_task(self._async_persist_managed_items())
