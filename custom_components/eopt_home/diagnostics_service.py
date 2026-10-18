"""Fork-only diagnostics: eopt_home.drop_connection.

Closes the TCP socket(s) to the controller so the automatic reconnect can be
tested. Sends nothing to the controller. Not intended for upstream.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SERVICE_DROP_CONNECTION = "drop_connection"


@callback
def async_register_drop_connection(hass: HomeAssistant) -> None:
    """Register the service once."""
    if hass.services.has_service(DOMAIN, SERVICE_DROP_CONNECTION):
        return

    async def _drop(call: ServiceCall) -> None:
        hubs = hass.data.get(DOMAIN, {})
        _LOGGER.warning("drop_connection called: closing %d controller socket(s) to test reconnect", len(hubs))
        for hub in hubs.values():
            await hub.force_reconnect()

    hass.services.async_register(DOMAIN, SERVICE_DROP_CONNECTION, _drop)
