"""Device registry upkeep for AMP instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, STALE_DEVICES_KEY

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import AmpCoordinatorData


def async_get_entry_device(
    dev_reg: dr.DeviceRegistry, entry: ConfigEntry, identifier: tuple[str, str]
) -> dr.DeviceEntry | None:
    """Return this entry's device with ``identifier``, if any.

    Newer Home Assistant no longer guarantees device identifiers are unique
    across config entries, so ``async_get_device`` is deprecated in favour of
    a lookup scoped to the owning entry. Older versions only have the former.
    """
    get_by_identifier = getattr(dev_reg, "async_get_device_by_identifier", None)
    if get_by_identifier is not None:
        return get_by_identifier(identifier, entry.entry_id)
    return dev_reg.async_get_device({identifier})


def _async_remove_entry_device(
    dev_reg: dr.DeviceRegistry, entry: ConfigEntry, device: dr.DeviceEntry
) -> None:
    """Remove a device of this entry from the device registry.

    Newer Home Assistant gives a device exactly one config entry, so it is
    removed outright; ``async_update_device(remove_config_entry_id=...)`` is
    deprecated there. Older versions (detected by the scoped lookup helper
    that arrived together with that change) still detach the entry instead.
    """
    if hasattr(dev_reg, "async_get_device_by_identifier"):
        dev_reg.async_remove_device(device.id)
    else:
        dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


@callback
def async_remove_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, data: AmpCoordinatorData
) -> None:
    """Remove devices for AMP instances that no longer exist.

    Removing a device also drops its entities and their customisations (names,
    areas, entity ids), and a single short answer from AMP looks exactly like
    deleted instances. So a device is only removed once it has been missing
    from two consecutive polls; the first sighting is just remembered. The
    memory lives in ``hass.data`` because a changed instance list reloads the
    entry, which would otherwise forget it.
    """
    keep = {(DOMAIN, iid) for iid in data.instances}
    keep |= {(DOMAIN, "amp_panel"), (DOMAIN, entry.entry_id)}
    dev_reg = dr.async_get(hass)
    pending: dict[str, set[str]] = hass.data.setdefault(DOMAIN, {}).setdefault(
        STALE_DEVICES_KEY, {}
    )
    previously_missing = pending.get(entry.entry_id, set())
    missing: set[str] = set()
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if device.identifiers & keep:
            continue
        if device.id in previously_missing:
            _async_remove_entry_device(dev_reg, entry, device)
        else:
            missing.add(device.id)
    pending[entry.entry_id] = missing
