"""The AMP integration."""

from __future__ import annotations

from datetime import timedelta
from logging import Logger, getLogger

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_loaded_integration

from .api import AmpApiClient
from .coordinator import AmpDataUpdateCoordinator
from .data import AmpData
from .entry import AMPConfigEntry

_PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]
LOGGER: Logger = getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, entry: AMPConfigEntry) -> bool:
    """Set up AMP from a config entry."""

    coordinator = AmpDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name="cubecoders",
        config_entry=entry,
        update_interval=timedelta(minutes=1),
    )

    entry.runtime_data = AmpData(
        coordinator=coordinator,
        client=AmpApiClient(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            host=entry.data[CONF_HOST],
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
    )

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AMPConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
