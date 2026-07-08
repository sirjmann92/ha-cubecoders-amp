"""The AMP integration."""

from __future__ import annotations

from datetime import timedelta
from logging import Logger, getLogger
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_loaded_integration

from .api import AmpApiClient
from .const import DOMAIN, STATIC_URL_BASE
from .coordinator import AmpDataUpdateCoordinator
from .data import AmpData
from .entry import AMPConfigEntry
from .services import async_setup_services, async_unload_services

_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.UPDATE,
]
LOGGER: Logger = getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, entry: AMPConfigEntry) -> bool:
    """Set up AMP from a config entry."""

    # Serve bundled assets (theme-neutral entity pictures). Guarded because
    # static paths cannot be registered twice across entry reloads.
    if not hass.data.setdefault(DOMAIN, {}).get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL_BASE, str(Path(__file__).parent / "static"), True
                )
            ]
        )
        hass.data[DOMAIN]["static_registered"] = True

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
    async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AMPConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if unload_ok and not any(
        other.entry_id != entry.entry_id
        for other in hass.config_entries.async_loaded_entries(entry.domain)
    ):
        async_unload_services(hass)
    return unload_ok
