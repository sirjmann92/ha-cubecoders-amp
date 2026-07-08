"""Update platform for the CubeCoders AMP integration."""

from __future__ import annotations

from homeassistant.components.update import UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STATIC_URL_BASE
from .entity import AMPEntity
from .entry import AMPConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: AMPConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the update platform."""
    async_add_entities([AmpPanelUpdateEntity(entry)])


class AmpPanelUpdateEntity(AMPEntity, UpdateEntity):
    """Shows the AMP panel's installed version and whether an update is available.

    Display-only: installing AMP updates from HA is intentionally not supported.
    """

    _attr_name = "AMP Panel"
    _attr_icon = "mdi:package-up"

    def __init__(self, entry: AMPConfigEntry) -> None:
        """Initialize the panel update entity."""
        super().__init__(entry.runtime_data.coordinator)
        self._attr_unique_id = f"{entry.entry_id}_amp_panel_update"

    @property
    def entity_picture(self) -> str:
        """Return a bundled, theme-neutral AMP logo.

        UpdateEntity's default points at the brand icon's light variant,
        which is unreadable in dark mode (the frontend never swaps entity
        pictures per theme). The bundled icon bakes the logo onto a dark
        chip so it reads on both themes.
        """
        return f"{STATIC_URL_BASE}/icon.png"

    @property
    def device_info(self) -> DeviceInfo:
        """Device representing the AMP panel (ADS controller) itself."""
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={("cubecoders", "amp_panel")},
            name="AMP Panel",
            manufacturer="CubeCoders",
            sw_version=data.panel_version if data is not None else None,
        )

    @property
    def installed_version(self) -> str | None:
        """Return the AMP version the panel is running."""
        data = self.coordinator.data
        return data.panel_version if data is not None else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest available AMP version.

        Equals installed_version when AMP reports no update, so HA shows
        "up to date"; None when update info could not be fetched.
        """
        data = self.coordinator.data
        if data is None:
            return None
        update = data.panel_update
        if update is not None and update.update_available and update.version:
            return update.version
        if update is not None:
            return data.panel_version
        return None

    @property
    def release_url(self) -> str | None:
        """Return the release notes URL for an available update."""
        data = self.coordinator.data
        if data is not None and data.panel_update is not None:
            return data.panel_update.release_notes_url
        return None
