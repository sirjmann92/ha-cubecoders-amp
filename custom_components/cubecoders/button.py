"""Button platform for the CubeCoders AMP integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
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
    """Set up the button platform."""
    instances = await entry.runtime_data.client.async_get_instances()
    async_add_entities(
        AmpRestartInstanceButton(entry, instance, build_device_info(instance))
        for instance in instances
        if instance.instance_name != "ADS"
    )


class AmpRestartInstanceButton(AmpInstanceEntity, ButtonEntity):
    """Button that restarts a running AMP instance via the ADS controller."""

    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(
        self,
        entry: AMPConfigEntry,
        instance: AmpBaseInstance,
        device: DeviceInfo,
    ) -> None:
        """Initialize the restart button."""
        super().__init__(entry.runtime_data.coordinator, instance, device)
        self._client = entry.runtime_data.client
        self._attr_unique_id = (
            f"{instance.instance_index}_{instance.instance_name}_restart_instance"
        )
        self._attr_name = f"{instance.instance_name} Restart Instance"

    @property
    def available(self) -> bool:
        """Restarting only makes sense while the instance is running."""
        data = self.instance_data
        return super().available and data is not None and data.running

    async def async_press(self) -> None:
        """Restart the instance."""
        try:
            await self._client.async_restart_instance(self.amp_instance_name)
        except AmpApiClientError as exception:
            raise HomeAssistantError(str(exception)) from exception
        await self.coordinator.async_request_refresh()
