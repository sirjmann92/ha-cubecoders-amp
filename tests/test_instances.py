"""Instances are keyed by AMP instance id, migrated from index ids, and reloaded on change."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.cubecoders.api import (
    AmpBaseInstance,
    AmpCoordinatorData,
    AmpExtendedInstance,
)
from custom_components.cubecoders.devices import (
    _async_remove_entry_device,
    async_get_entry_device,
)

DOMAIN = "cubecoders"

# friendly name -> (AMP instance id, AMP instance name, CPU %)
SERVERS = {
    "ADS": ("ads-guid", "ADS01", 1),
    "KF2 01": ("kf2-guid", "KF20101", 11),
    "Lemon Server": ("lemon-guid", "LemonServer01", 55),
    "PZ 04 mods": ("pz4-guid", "PZ04mods01", 44),
    "Valheim 01": ("val-guid", "Valheim0101", 77),
}


def _build(names: list[str]) -> tuple[list[AmpBaseInstance], AmpCoordinatorData]:
    """Mimic AMP: instances come back sorted alphabetically."""
    base, extended = [], {}
    for index, name in enumerate(sorted(names, key=str.lower)):
        iid, amp_name, cpu = SERVERS[name]
        base.append(AmpBaseInstance(name, index, amp_name, iid))
        extended[iid] = AmpExtendedInstance(
            instance_name=name,
            instance_index=index,
            amp_instance_name=amp_name,
            instance_id=iid,
            active_users=0,
            players=None,
            max_active_users=8,
            cpu_usage_percentage=cpu,
            memory_usage_mb=1024,
            app_state="ready",
            address=None,
            running=True,
            amp_version="2.6",
            module="GenericModule",
        )
    return base, AmpCoordinatorData(
        instances=extended, panel_version="2.6", panel_update=None
    )


class _Servers(list):
    """The instance list the fake panel reports; ``once`` holds one-off answers."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.once: list[list[str]] = []


@pytest.fixture
def amp_servers():
    """The instance list the fake AMP panel reports; tests mutate it.

    Append a list to ``amp_servers.once`` to make the next poll answer with
    that list instead (e.g. a short response), after which it reverts.
    """
    servers = _Servers(["ADS", "KF2 01", "PZ 04 mods", "Valheim 01"])

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def async_get_instances(self):
            return _build(servers)[0]

        async def async_get_data(self):
            return _build(servers.once.pop(0) if servers.once else servers)[1]

    with patch("custom_components.cubecoders.AmpApiClient", FakeClient):
        yield servers


async def _refresh(hass: HomeAssistant, minutes: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done()
    await hass.async_block_till_done()


async def test_migration_and_auto_reload(hass: HomeAssistant, amp_servers) -> None:
    """Index-based ids migrate in place; adding/removing instances reloads cleanly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://amp:8080", "username": "u", "password": "p"},
    )
    entry.add_to_hass(hass)

    # Registry entries as created by the previous, index-keyed version.
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    old_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "PZ 04 mods")},
        name="PZ 04 mods",
    )
    dev_reg.async_update_device(old_device.id, area_id="office")
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        "2_PZ 04 mods_cpu_usage_percentage",
        config_entry=entry,
        suggested_object_id="pz_04_mods_cpu_usage",
        device_id=old_device.id,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Entity id, device and area survive; unique id now uses the instance id.
    migrated = ent_reg.async_get("sensor.pz_04_mods_cpu_usage")
    assert migrated.unique_id == "pz4-guid_cpu_usage_percentage"
    device = dev_reg.async_get_device({(DOMAIN, "pz4-guid")})
    assert device.id == old_device.id
    assert device.area_id == "office"
    assert not any(
        e.entity_id.endswith("_2")
        for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    )
    assert hass.states.get("sensor.pz_04_mods_cpu_usage").state == "44"

    # A new instance sorting before PZ is picked up without shifting PZ's data.
    amp_servers.append("Lemon Server")
    await _refresh(hass, 2)
    assert hass.states.get("sensor.lemon_server_cpu_usage").state == "55"
    assert hass.states.get("sensor.pz_04_mods_cpu_usage").state == "44"
    assert hass.states.get("sensor.valheim_01_cpu_usage").state == "77"

    # A deleted instance's device is removed.
    amp_servers.remove("KF2 01")
    await _refresh(hass, 4)
    assert dev_reg.async_get_device({(DOMAIN, "kf2-guid")}) is None
    assert hass.states.get("sensor.pz_04_mods_cpu_usage").state == "44"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://amp:8080", "username": "u", "password": "p"},
    )


async def test_short_response_keeps_devices_and_customisations(
    hass: HomeAssistant, amp_servers
) -> None:
    """One short answer from AMP must not delete devices or entity customisations."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    kf2 = dev_reg.async_get_device({(DOMAIN, "kf2-guid")})
    dev_reg.async_update_device(kf2.id, area_id="garage")
    ent_reg.async_update_entity("sensor.kf2_01_cpu_usage", name="My KF2 CPU")

    # The next poll drops KF2 (the reload's own setup poll answers in full again).
    amp_servers.once.append(["ADS", "PZ 04 mods", "Valheim 01"])
    await _refresh(hass, 2)

    kept = dev_reg.async_get_device({(DOMAIN, "kf2-guid")})
    assert kept is not None
    assert kept.id == kf2.id
    assert kept.area_id == "garage"
    assert ent_reg.async_get("sensor.kf2_01_cpu_usage").name == "My KF2 CPU"
    assert hass.states.get("sensor.kf2_01_cpu_usage").state == "11"

    # Having come back, it takes two fresh misses to count again: one is not enough.
    amp_servers.once.append(["ADS", "PZ 04 mods", "Valheim 01"])
    await _refresh(hass, 4)
    assert dev_reg.async_get_device({(DOMAIN, "kf2-guid")}) is not None


async def test_stale_device_removed_on_second_poll(
    hass: HomeAssistant, amp_servers
) -> None:
    """A device already stale at startup goes on the second poll; kept ones stay."""
    entry = _entry()
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    ghost, panel, entry_device = (
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, ident)}, name=ident
        )
        for ident in ("ghost-guid", "amp_panel", entry.entry_id)
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert dev_reg.async_get(ghost.id) is not None  # first sighting only

    await _refresh(hass, 2)
    assert dev_reg.async_get(ghost.id) is None
    assert dev_reg.async_get(panel.id) is not None
    assert dev_reg.async_get(entry_device.id) is not None
    assert dev_reg.async_get_device({(DOMAIN, "kf2-guid")}) is not None

    await _refresh(hass, 4)
    assert dev_reg.async_get(panel.id) is not None
    assert dev_reg.async_get(entry_device.id) is not None


async def test_stale_memory_forgotten_with_entry(
    hass: HomeAssistant, amp_servers
) -> None:
    """Removing the config entry drops its stale-device memory."""
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id in hass.data[DOMAIN]["stale_devices"]

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data[DOMAIN]["stale_devices"]


def test_device_helpers_use_scoped_api_when_available() -> None:
    """Newer Home Assistant: entry-scoped lookup, and remove the device outright."""
    entry = SimpleNamespace(entry_id="entry-1")
    device = SimpleNamespace(id="dev-1")
    dev_reg = MagicMock(
        spec=[
            "async_get_device",
            "async_get_device_by_identifier",
            "async_remove_device",
            "async_update_device",
        ]
    )

    found = async_get_entry_device(dev_reg, entry, (DOMAIN, "iid"))
    assert found is dev_reg.async_get_device_by_identifier.return_value
    dev_reg.async_get_device_by_identifier.assert_called_once_with(
        (DOMAIN, "iid"), "entry-1"
    )
    dev_reg.async_get_device.assert_not_called()

    _async_remove_entry_device(dev_reg, entry, device)
    dev_reg.async_remove_device.assert_called_once_with("dev-1")
    dev_reg.async_update_device.assert_not_called()


def test_device_helpers_fall_back_on_older_home_assistant() -> None:
    """Older Home Assistant: global lookup, and detach the config entry."""
    entry = SimpleNamespace(entry_id="entry-1")
    device = SimpleNamespace(id="dev-1")
    dev_reg = MagicMock(spec=["async_get_device", "async_update_device"])

    found = async_get_entry_device(dev_reg, entry, (DOMAIN, "iid"))
    assert found is dev_reg.async_get_device.return_value
    dev_reg.async_get_device.assert_called_once_with({(DOMAIN, "iid")})

    _async_remove_entry_device(dev_reg, entry, device)
    dev_reg.async_update_device.assert_called_once_with(
        "dev-1", remove_config_entry_id="entry-1"
    )
