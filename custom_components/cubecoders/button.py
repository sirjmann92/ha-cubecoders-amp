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
    entities: list[ButtonEntity] = []
    for instance in instances:
        if instance.instance_name == "ADS":
            continue
        device = build_device_info(instance)
        entities.extend(
            [
                AmpInstanceButton(
                    entry,
                    instance,
                    device,
                    name="Restart Instance",
                    # Keep the pre-1.4 unique id for this button.
                    key="restart_instance",
                    client_method="async_restart_instance",
                    device_class=ButtonDeviceClass.RESTART,
                ),
                AmpInstanceButton(
                    entry,
                    instance,
                    device,
                    name="Restart Application",
                    key="restart_application",
                    client_method="async_restart_application",
                    device_class=ButtonDeviceClass.RESTART,
                    icon="mdi:gamepad-variant",
                ),
                AmpInstanceButton(
                    entry,
                    instance,
                    device,
                    name="Update Game Server",
                    key="update_game_server",
                    client_method="async_upgrade_instance",
                    device_class=ButtonDeviceClass.UPDATE,
                ),
            ]
        )
    async_add_entities(entities)


class AmpInstanceButton(AmpInstanceEntity, ButtonEntity):
    """Button that runs one client action against a running AMP instance."""

    def __init__(
        self,
        entry: AMPConfigEntry,
        instance: AmpBaseInstance,
        device: DeviceInfo,
        name: str,
        key: str,
        client_method: str,
        device_class: ButtonDeviceClass | None = None,
        icon: str | None = None,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry.runtime_data.coordinator, instance, device)
        self._client = entry.runtime_data.client
        self._client_method = client_method
        self._attr_unique_id = (
            f"{instance.instance_index}_{instance.instance_name}_{key}"
        )
        self._attr_name = f"{instance.instance_name} {name}"
        self._attr_device_class = device_class
        if icon is not None:
            self._attr_icon = icon

    @property
    def available(self) -> bool:
        """These actions only make sense while the instance is running."""
        data = self.instance_data
        return super().available and data is not None and data.running

    async def async_press(self) -> None:
        """Run the action."""
        try:
            await getattr(self._client, self._client_method)(self.amp_instance_name)
        except AmpApiClientError as exception:
            raise HomeAssistantError(str(exception)) from exception
        await self.coordinator.async_request_refresh()
