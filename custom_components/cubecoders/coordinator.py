"""DataUpdateCoordinator for the CubeCoders AMP integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AmpApiClientAuthenticationError, AmpApiClientError, AmpCoordinatorData

if TYPE_CHECKING:
    from .data import AmpData

type AMPConfigEntry = ConfigEntry[AmpData]

EVENT_PLAYER_JOINED = "cubecoders_player_joined"
EVENT_PLAYER_LEFT = "cubecoders_player_left"


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class AmpDataUpdateCoordinator(DataUpdateCoordinator[AmpCoordinatorData]):
    """Class to manage fetching data from the API."""

    config_entry: AMPConfigEntry

    async def _async_update_data(self) -> Any:
        """Update data via library."""
        try:
            data = await self.config_entry.runtime_data.client.async_get_data()
        except AmpApiClientAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except AmpApiClientError as exception:
            raise UpdateFailed(exception) from exception

        self._process_player_transitions(previous=self.data, new=data)
        return data

    def _process_player_transitions(
        self, previous: AmpCoordinatorData | None, new: AmpCoordinatorData
    ) -> None:
        """Fire join/leave events and carry forward state across refreshes.

        Both "how long has this instance been empty" and "when was its last
        backup" can only be refreshed while the instance is running, so a
        stopped instance keeps its previous value instead of losing it.
        Events are only fired when a previous refresh exists, so a Home
        Assistant restart doesn't announce every already-connected player.
        """
        previous_by_name = (
            {
                inst.amp_instance_name: inst
                for inst in previous.instances.values()
            }
            if previous is not None
            else {}
        )
        now = dt_util.utcnow()

        for instance in new.instances.values():
            prev = previous_by_name.get(instance.amp_instance_name)

            if instance.running and instance.active_users == 0 and not instance.player_list:
                was_empty = (
                    prev is not None
                    and prev.running
                    and prev.empty_since is not None
                )
                instance.empty_since = prev.empty_since if was_empty else now
            else:
                instance.empty_since = None

            if (
                instance.last_backup_at is None
                and prev is not None
                and prev.last_backup_at is not None
            ):
                instance.last_backup_at = prev.last_backup_at
                instance.last_backup_name = prev.last_backup_name

            if prev is None:
                continue
            previous_players = set(prev.player_list)
            current_players = set(instance.player_list)
            event_data = {
                "instance_name": instance.instance_name,
                "amp_instance_name": instance.amp_instance_name,
            }
            for player in sorted(current_players - previous_players):
                self.hass.bus.async_fire(
                    EVENT_PLAYER_JOINED, {**event_data, "player": player}
                )
            for player in sorted(previous_players - current_players):
                self.hass.bus.async_fire(
                    EVENT_PLAYER_LEFT, {**event_data, "player": player}
                )
