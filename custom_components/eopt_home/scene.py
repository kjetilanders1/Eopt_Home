"""Scene platform for Eopt Home integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene as SceneEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .sensio_lib import Hub, Scene, SensioException

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eopt Home scenes from a config entry."""
    hub: Hub = hass.data[DOMAIN][entry.entry_id]
    scenes = hub.get_scenes()

    entities = [SensioSceneEntity(scene, hub, entry) for scene in scenes]
    async_add_entities(entities)
    _LOGGER.debug("Added %d Eopt Home scene entities", len(entities))


class SensioSceneEntity(SceneEntity):
    """Representation of a Sensio/Eopt Home scene."""

    _attr_has_entity_name = True

    _attr_should_poll = False

    def __init__(self, scene: Scene, hub: Hub, entry: ConfigEntry) -> None:
        """Initialize the scene entity."""
        self._scene = scene
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_{scene.unique_id}"
        self._attr_name = scene.name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Eopt Home ({entry.data.get('project_name', 'Hub')})",
            "manufacturer": "Eopt Home",
            "model": "Sensio Controller",
        }

    async def async_added_to_hass(self) -> None:
        """Track controller availability."""
        self.async_on_remove(self._hub.add_availability_listener(self._handle_availability))

    @callback
    def _handle_availability(self, available: bool) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable only if the controller connection stays down past the grace period."""
        return self._hub.available

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        try:
            await self._scene.activate()
        except SensioException as err:
            raise HomeAssistantError(f"Could not activate {self.name}: {err}") from err
