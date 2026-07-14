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

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import storage
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, STORAGE_KEY_REPAIRS, STORAGE_KEY_UPDATES, STORAGE_VERSION

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
            UpdateVisibilitySwitch(hass, entry, update_store),
            RepairVisibilitySwitch(hass, entry, repair_store),
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


async def _async_require_admin(
    hass: HomeAssistant,
    context: Context | None,
) -> None:
    """Require admin access for user-initiated visibility changes."""
    if context is None or context.user_id is None:
        return

    user = await hass.auth.async_get_user(context.user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(context=context)


# ---------------------------------------------------------------------------
# Switch 1 – Updates
# ---------------------------------------------------------------------------

class UpdateVisibilitySwitch(RestoreEntity, SwitchEntity):
    """Global switch: show/hide update entities in the Settings badge.

    Tracks which entity_ids it hides so it only restores exactly those
    on turn-on; externally hidden entities are never touched.
    """

    _attr_has_entity_name = True
    _attr_name = "Toon updates in Instellingen"
    _attr_icon = "mdi:package-up"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: storage.Store,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._store = store
        self._attr_unique_id = f"{DOMAIN}_show_updates_in_settings"
        self._is_on: bool = True
        self._hidden_by_us: set[str] = set()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(
            stored.get("hidden_entity_ids"), list
        ):
            self._hidden_by_us = {
                entity_id
                for entity_id in stored["hidden_entity_ids"]
                if isinstance(entity_id, str) and entity_id.startswith("update.")
            }

        last_state = await self.async_get_last_state()
        self._is_on = last_state.state == "on" if last_state is not None else True

        await self._sync_visibility()

        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._handle_registry_change,
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await _async_require_admin(self.hass, self._context)
        self._is_on = True
        await self._sync_visibility()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _async_require_admin(self.hass, self._context)
        self._is_on = False
        await self._sync_visibility()
        self.async_write_ha_state()

    async def _sync_visibility(self) -> None:
        registry = er.async_get(self.hass)

        if self._is_on:
            for entity_id in list(self._hidden_by_us):
                reg_entry = registry.async_get(entity_id)
                if reg_entry is None:
                    self._hidden_by_us.discard(entity_id)
                    continue
                if reg_entry.domain == "update" and reg_entry.hidden_by == _HIDDEN_BY:
                    registry.async_update_entity(entity_id, hidden_by=None)
                    _LOGGER.debug("Un-hiding update entity: %s", entity_id)
                self._hidden_by_us.discard(entity_id)
        else:
            for reg_entry in registry.entities.values():
                if reg_entry.domain == "update" and reg_entry.hidden_by is None:
                    registry.async_update_entity(
                        reg_entry.entity_id, hidden_by=_HIDDEN_BY
                    )
                    self._hidden_by_us.add(reg_entry.entity_id)
                    _LOGGER.debug("Hiding update entity: %s", reg_entry.entity_id)

        await self._persist()

    async def _persist(self) -> None:
        await self._store.async_save({"hidden_entity_ids": list(self._hidden_by_us)})

    @callback
    def _handle_registry_change(self, event: Any) -> None:
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

        registry.async_update_entity(entity_id, hidden_by=_HIDDEN_BY)
        self._hidden_by_us.add(entity_id)
        _LOGGER.debug("Hiding newly registered update entity: %s", entity_id)
        self.hass.async_create_task(self._persist())


# ---------------------------------------------------------------------------
# Switch 2 – Repairs
# ---------------------------------------------------------------------------

class RepairVisibilitySwitch(RestoreEntity, SwitchEntity):
    """Global switch: show/hide repair issues in the Settings badge.

    When OFF, all active (non-ignored) repair issues are marked as ignored,
    which removes the Settings badge.  The Updates page equivalent for repairs
    (Settings → Repairs, /config/repairs) still shows all issues including
    ignored ones, so users can always find and act on them.

    Tracks which (domain, issue_id) tuples it ignored so that on turn-on it
    restores only those; issues already ignored by something else are untouched.
    """

    _attr_has_entity_name = True
    _attr_name = "Toon reparaties in Instellingen"
    _attr_icon = "mdi:wrench-clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: storage.Store,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._store = store
        self._attr_unique_id = f"{DOMAIN}_show_repairs_in_settings"
        self._is_on: bool = True
        # Set of (domain, issue_id) tuples we ignored
        self._ignored_by_us: set[tuple[str, str]] = set()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        stored = await self._store.async_load()
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

        last_state = await self.async_get_last_state()
        self._is_on = last_state.state == "on" if last_state is not None else True

        await self._sync_visibility()

        # Listen for new repair issues
        self.async_on_remove(
            self.hass.bus.async_listen(
                "repairs_issue_registry_updated",
                self._handle_repairs_change,
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await _async_require_admin(self.hass, self._context)
        self._is_on = True
        await self._sync_visibility()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _async_require_admin(self.hass, self._context)
        self._is_on = False
        await self._sync_visibility()
        self.async_write_ha_state()

    async def _sync_visibility(self) -> None:
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
                    issue_registry.async_ignore(domain, issue_id, False)
                    _LOGGER.debug("Un-ignoring repair issue: %s/%s", domain, issue_id)
                self._ignored_by_us.discard(issue_key)
        else:
            # Ignore all currently active (non-ignored) issues
            for (domain, issue_id), issue in issue_registry.issues.items():
                if not issue.ignored and not issue.dismissed_version:
                    issue_registry.async_ignore(domain, issue_id, True)
                    self._ignored_by_us.add((domain, issue_id))
                    _LOGGER.debug("Ignoring repair issue: %s/%s", domain, issue_id)

        await self._persist()

    async def _persist(self) -> None:
        await self._store.async_save(
            {"ignored_issue_ids": [list(item) for item in self._ignored_by_us]}
        )

    @callback
    def _handle_repairs_change(self, event: Any) -> None:
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

        issue_registry.async_ignore(domain, issue_id, True)
        self._ignored_by_us.add((domain, issue_id))
        _LOGGER.debug("Ignoring newly created repair issue: %s/%s", domain, issue_id)
        self.hass.async_create_task(self._persist())
