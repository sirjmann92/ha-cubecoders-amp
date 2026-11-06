"""Instances are keyed by AMP instance id, migrated from index ids, and reloaded on change."""

from datetime import timedelta
from unittest.mock import patch

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


@pytest.fixture
def amp_servers():
    """The instance list the fake AMP panel reports; tests mutate it."""
    servers = ["ADS", "KF2 01", "PZ 04 mods", "Valheim 01"]

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def async_get_instances(self):
            return _build(servers)[0]

        async def async_get_data(self):
            return _build(servers)[1]

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
