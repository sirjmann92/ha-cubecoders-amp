"""Custom services for the CubeCoders AMP integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import AmpApiClient, AmpApiClientError
from .const import DOMAIN

ATTR_INSTANCE = "instance"
ATTR_COMMAND = "command"
ATTR_PLAYER = "player"

SERVICE_SEND_COMMAND = "send_command"

COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_INSTANCE): cv.string,
        vol.Required(ATTR_COMMAND): cv.string,
    }
)
PLAYER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_INSTANCE): cv.string,
        vol.Required(ATTR_PLAYER): cv.string,
    }
)

# HA service name -> client Minecraft action.
MC_SERVICES = {
    "mc_kick_player": "kick",
    "mc_ban_player": "ban",
    "mc_smite_player": "smite",
    "mc_whitelist_add": "whitelist_add",
    "mc_whitelist_remove": "whitelist_remove",
    "mc_op_player": "op",
    "mc_deop_player": "deop",
}


def _get_client(hass: HomeAssistant) -> AmpApiClient:
    """Return the client of the loaded config entry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data.client
    msg = "The CubeCoders AMP integration is not loaded"
    raise HomeAssistantError(msg)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        return

    async def handle_send_command(call: ServiceCall) -> None:
        try:
            await _get_client(hass).async_send_console_command(
                call.data[ATTR_INSTANCE], call.data[ATTR_COMMAND]
            )
        except AmpApiClientError as exception:
            raise HomeAssistantError(str(exception)) from exception

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_COMMAND, handle_send_command, schema=COMMAND_SCHEMA
    )

    def make_mc_handler(action: str):  # noqa: ANN202
        async def handle_mc(call: ServiceCall) -> None:
            try:
                await _get_client(hass).async_mc_player_action(
                    call.data[ATTR_INSTANCE], action, call.data[ATTR_PLAYER]
                )
            except AmpApiClientError as exception:
                raise HomeAssistantError(str(exception)) from exception

        return handle_mc

    for service_name, action in MC_SERVICES.items():
        hass.services.async_register(
            DOMAIN, service_name, make_mc_handler(action), schema=PLAYER_SCHEMA
        )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the integration's services."""
    hass.services.async_remove(DOMAIN, SERVICE_SEND_COMMAND)
    for service_name in MC_SERVICES:
        hass.services.async_remove(DOMAIN, service_name)
