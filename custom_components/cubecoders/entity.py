"""Module for CubeCoders AMP integration entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AmpBaseInstance, AmpExtendedInstance
from .coordinator import AmpDataUpdateCoordinator


def build_device_info(instance: AmpBaseInstance) -> DeviceInfo:
    """Build the device registry entry shared by all of an instance's entities."""
    return DeviceInfo(
        identifiers={("cubecoders", instance.instance_name)},
        name=instance.instance_name,
        manufacturer="CubeCoders",
    )


class AMPEntity(CoordinatorEntity[AmpDataUpdateCoordinator]):
    """BlueprintEntity class."""

    _attr_attribution = "Attribution"

    def __init__(self, coordinator: AmpDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    coordinator.config_entry.domain,
                    coordinator.config_entry.entry_id,
                ),
            },
        )


class AmpInstanceEntity(AMPEntity):
    """Entity tied to a single AMP instance in the coordinator data."""

    def __init__(
        self,
        coordinator: AmpDataUpdateCoordinator,
        instance: AmpBaseInstance,
        device: DeviceInfo,
    ) -> None:
        """Initialize the per-instance entity."""
        super().__init__(coordinator)
        self.index = instance.instance_index
        self.amp_instance_name = instance.amp_instance_name
        self.device = device

    @property
    def instance_data(self) -> AmpExtendedInstance | None:
        """Return this instance's entry in the coordinator data, if present."""
        return (self.coordinator.data or {}).get(self.index)

    @property
    def available(self) -> bool:
        """Return True if the instance was present in the last update."""
        return super().available and self.instance_data is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Returns the device information."""
        return self.device
