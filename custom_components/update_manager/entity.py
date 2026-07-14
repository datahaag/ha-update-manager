"""Shared entity helpers for Update Manager."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import Context, Event, HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import storage
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity


class VisibilitySwitchEntity(RestoreEntity, SwitchEntity):
    """Base entity for switches that manage Settings visibility."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _registry_event: str

    def __init__(
        self,
        hass: HomeAssistant,
        store: storage.Store,
        unique_id: str,
    ) -> None:
        self.hass = hass
        self._store = store
        self._attr_unique_id = unique_id
        self._is_on = True

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_restore_managed_items()

        last_state = await self.async_get_last_state()
        self._is_on = last_state is None or last_state.state == STATE_ON

        await self._async_sync_visibility()
        self.async_on_remove(
            self.hass.bus.async_listen(
                self._registry_event,
                self._handle_registry_change,
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_state(False)

    async def _async_set_state(self, is_on: bool) -> None:
        await self._async_require_admin(self._context)
        self._is_on = is_on
        await self._async_sync_visibility()
        self.async_write_ha_state()

    async def _async_require_admin(self, context: Context | None) -> None:
        if context is None or context.user_id is None:
            return

        user = await self.hass.auth.async_get_user(context.user_id)
        if user is None or not user.is_admin:
            raise Unauthorized(context=context)

    async def _async_restore_managed_items(self) -> None:
        raise NotImplementedError

    async def _async_sync_visibility(self) -> None:
        raise NotImplementedError

    def _handle_registry_change(self, event: Event) -> None:
        raise NotImplementedError
