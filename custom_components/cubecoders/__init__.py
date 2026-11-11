"""The AMP integration."""

from __future__ import annotations

from datetime import timedelta
from logging import Logger, getLogger
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration

from .api import AmpApiClient, AmpCoordinatorData
from .const import CONF_TOTP_SECRET, DOMAIN, STATIC_URL_BASE
from .coordinator import AmpDataUpdateCoordinator
from .data import AmpData
from .entry import AMPConfigEntry
from .services import async_setup_services, async_unload_services
from .twofactor import set_secret

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

    # Must be set before the first API call; empty means no 2FA.
    set_secret(entry.data.get(CONF_TOTP_SECRET, ""))

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
    _async_migrate_to_instance_ids(hass, entry, coordinator.data)
    _async_remove_stale_devices(hass, entry, coordinator.data)
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


@callback
def _async_migrate_to_instance_ids(
    hass: HomeAssistant, entry: AMPConfigEntry, data: AmpCoordinatorData
) -> None:
    """Move entities/devices from list-position ids to AMP instance ids.

    Older versions built unique ids as "<list index>_<friendly name>_<key>"
    and device identifiers from the friendly name. Rewriting them in place
    keeps entity ids, history and area assignments. Safe to run every setup:
    already-migrated entries simply don't match.
    """
    old_prefix_to_id = {
        f"{inst.instance_index}_{inst.instance_name}_": iid
        for iid, inst in data.instances.items()
    }

    @callback
    def migrate_entity(reg_entry: er.RegistryEntry) -> dict[str, str] | None:
        for old_prefix, iid in old_prefix_to_id.items():
            if reg_entry.unique_id.startswith(old_prefix):
                return {"unique_id": f"{iid}_{reg_entry.unique_id[len(old_prefix):]}"}
        return None

    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        update = migrate_entity(reg_entry)
        if update is not None and not ent_reg.async_get_entity_id(
            reg_entry.domain, DOMAIN, update["unique_id"]
        ):
            ent_reg.async_update_entity(
                reg_entry.entity_id, new_unique_id=update["unique_id"]
            )

    name_to_id = {inst.instance_name: iid for iid, inst in data.instances.items()}
    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for domain, ident in device.identifiers:
            iid = name_to_id.get(ident) if domain == DOMAIN else None
            if iid and iid != ident and not dev_reg.async_get_device({(DOMAIN, iid)}):
                dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, iid)})
                break


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: AMPConfigEntry, data: AmpCoordinatorData
) -> None:
    """Remove devices for AMP instances that no longer exist."""
    keep = {(DOMAIN, iid) for iid in data.instances}
    keep |= {(DOMAIN, "amp_panel"), (DOMAIN, entry.entry_id)}
    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if not device.identifiers & keep:
            dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
