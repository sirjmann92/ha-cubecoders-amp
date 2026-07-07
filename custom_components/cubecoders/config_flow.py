"""Config flow for the AMP integration."""

from __future__ import annotations

import logging
import socket
from typing import Any
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol
from ampapi import ADSModule, Bridge
from ampapi.dataclass import APIParams

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def normalize_host(host: str) -> str:
    """Validate that the host is a full http(s) URL and normalize it.

    aiohttp no longer accepts schemeless URLs, and defaulting to a scheme is
    unsafe because many AMP panels sit behind an https reverse proxy, so an
    explicit scheme is required.
    """
    host = host.strip().rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidHost
    return host


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    data[CONF_HOST] = normalize_host(data[CONF_HOST])

    # Bridge is a process-wide singleton in ampapi; the entry is reloaded
    # after a successful (re)configure, so it picks these params back up.
    Bridge(
        api_params=APIParams(
            url=data[CONF_HOST],
            user=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
        )
    )
    try:
        await ADSModule().get_instances()
    except PermissionError as exception:
        raise InvalidAuth from exception
    except (
        aiohttp.ClientError,
        socket.gaierror,
        ConnectionError,
        TimeoutError,
        ValueError,
    ) as exception:
        raise CannotConnect from exception

    return {"title": "AMP"}


class AMPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AMP."""

    VERSION = 1

    async def _async_validate(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate user input, returning (info, errors)."""
        errors: dict[str, str] = {}
        try:
            info = await validate_input(self.hass, user_input)
        except InvalidHost:
            errors[CONF_HOST] = "invalid_host"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return info, errors
        return None, errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._async_validate(user_input)
            if info is not None:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._async_validate(user_input)
            if info is not None:
                return self.async_update_reload_and_abort(entry, data=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )


class InvalidHost(HomeAssistantError):
    """Error to indicate the host is not a valid http(s) URL."""


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
