"""Switch platform for the CubeCoders AMP integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import AmpApiClientError, AmpBaseInstance
from .entity import AmpInstanceEntity, build_device_info
from .entry import AMPConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: AMPConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    instances = await entry.runtime_data.client.async_get_instances()
    async_add_entities(
        AmpInstanceSwitch(entry, instance, build_device_info(instance))
        for instance in instances
        if instance.instance_name != "ADS"
    )


class AmpInstanceSwitch(AmpInstanceEntity, SwitchEntity):
    """Switch that starts/stops an AMP instance via the ADS controller."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:server"

    def __init__(
        self,
        entry: AMPConfigEntry,
        instance: AmpBaseInstance,
        device: DeviceInfo,
    ) -> None:
        """Initialize the instance switch."""
        super().__init__(entry.runtime_data.coordinator, instance, device)
        self._client = entry.runtime_data.client
        self._attr_unique_id = (
            f"{instance.instance_index}_{instance.instance_name}_instance_running"
        )
        self._attr_name = f"{instance.instance_name} Instance"

    @property
    def is_on(self) -> bool | None:
        """Return True if the instance is running."""
        data = self.instance_data
        return data.running if data is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the instance."""
        await self._async_set_running(running=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the instance."""
        await self._async_set_running(running=False)

    async def _async_set_running(self, *, running: bool) -> None:
        try:
            if running:
                await self._client.async_start_instance(self.amp_instance_name)
            else:
                await self._client.async_stop_instance(self.amp_instance_name)
        except AmpApiClientError as exception:
            raise HomeAssistantError(str(exception)) from exception

        # Optimistically flip the state so the UI responds immediately; the
        # next coordinator poll reports AMP's actual state.
        data = self.instance_data
        if data is not None:
            data.running = running
            self.coordinator.async_set_updated_data(self.coordinator.data)
        await self.coordinator.async_request_refresh()
