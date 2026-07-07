"""AMP API Client."""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass

import aiohttp
from ampapi import ADSModule, AMPInstance, Bridge, Core
from ampapi.dataclass import (
    ActionResult,
    APIParams,
    Instance,
    UpdateInfo,
    VersionInfo,
)

_LOGGER = logging.getLogger(__name__)


class AmpApiClientError(Exception):
    """Exception to indicate a general API error."""


class AmpApiClientCommunicationError(
    AmpApiClientError,
):
    """Exception to indicate a communication error."""


class AmpApiClientAuthenticationError(
    AmpApiClientError,
):
    """Exception to indicate an authentication error."""


@dataclass
class AmpBaseInstance:
    """Base instance class for AMP.

    instance_name is the friendly (display) name and is part of entity unique
    ids; amp_instance_name is the real AMP instance name, which is what the
    ADSModule start/stop/restart endpoints expect.
    """

    instance_name: str
    instance_index: int
    amp_instance_name: str


@dataclass
class AmpExtendedInstance(AmpBaseInstance):
    """Represents an extended instance of AMP (Application Management Panel)."""

    active_users: int
    players: str | None
    max_active_users: int
    cpu_usage_percentage: int
    memory_usage_mb: int
    app_state: str
    address: str | None
    running: bool
    amp_version: str | None


@dataclass
class AmpPanelUpdate:
    """AMP panel update availability, from Core/GetUpdateInfo."""

    update_available: bool
    version: str | None
    release_notes_url: str | None


@dataclass
class AmpCoordinatorData:
    """Everything one coordinator refresh collects."""

    instances: dict[int, AmpExtendedInstance]
    panel_version: str | None
    panel_update: AmpPanelUpdate | None


def format_amp_version(version: VersionInfo | str | dict | None) -> str | None:
    """Render the amp_version field (VersionInfo dataclass or string) as a string."""
    if version is None:
        return None
    if isinstance(version, VersionInfo):
        return f"{version.major}.{version.minor}.{version.revision}.{version.minor_revision}"
    return str(version)


class AmpApiClient:
    """AMP API Client."""

    def __init__(
        self,
        username: str,
        password: str,
        host: str,
    ) -> None:
        """AMP API Client."""
        self._username = username
        self._password = password
        self._host = host
        params = APIParams(
            url=host,
            user=username,
            password=password,
        )
        Bridge(api_params=params)  # stores params statically so available globally
        self.ads: ADSModule = ADSModule()
        # instance_id defaults to "0", which targets the panel/controller itself.
        self.core: Core = Core()

    async def async_get_instances(self) -> list[AmpBaseInstance]:
        """Asynchronously retrieves a list of AMP base instances.

        This method fetches the available instances from the ADS
        and returns a list of `AmpBaseInstance` objects, each containing the instance name and index.

        Returns:
            list[AmpBaseInstance]: A list of AMP base instances.

        """
        instances = (await self.ads.get_instances())[0].available_instances
        return [
            AmpBaseInstance(
                instance_name=instance.friendly_name,
                instance_index=index,
                amp_instance_name=instance.instance_name,
            )
            for index, instance in enumerate(instances)
        ]

    async def async_start_instance(self, amp_instance_name: str) -> None:
        """Start an instance via the ADS controller (works on stopped instances)."""
        await self._async_instance_action("start", amp_instance_name)

    async def async_stop_instance(self, amp_instance_name: str) -> None:
        """Stop an instance via the ADS controller."""
        await self._async_instance_action("stop", amp_instance_name)

    async def async_restart_instance(self, amp_instance_name: str) -> None:
        """Restart an instance via the ADS controller."""
        await self._async_instance_action("restart", amp_instance_name)

    async def _async_instance_action(self, action: str, amp_instance_name: str) -> None:
        """Run an ADS-level start/stop/restart action on an instance."""
        try:
            result = await getattr(self.ads, f"{action}_instance")(
                instance_name=amp_instance_name, format_data=True
            )
        except PermissionError as exception:
            msg = f"Authentication failed - {exception}"
            raise AmpApiClientAuthenticationError(msg) from exception
        except (
            aiohttp.ClientError,
            socket.gaierror,
            ConnectionError,
            TimeoutError,
            ValueError,
        ) as exception:
            msg = f"Failed to {action} instance {amp_instance_name} - {exception}"
            raise AmpApiClientCommunicationError(msg) from exception

        if isinstance(result, ActionResult) and result.status is False:
            msg = (
                f"AMP refused to {action} instance {amp_instance_name}:"
                f" {result.reason or 'no reason given'}"
            )
            raise AmpApiClientError(msg)

    async def async_get_data(self) -> AmpCoordinatorData:
        """Get data from the API for every instance, plus panel-level info.

        A stopped or unreachable instance must never fail the whole refresh:
        stopped instances are populated from the get_instances() payload only,
        and any per-instance error degrades to that same baseline data.
        """
        try:
            all_instances = (await self.ads.get_instances())[0].available_instances
        except PermissionError as exception:
            msg = f"Authentication failed - {exception}"
            raise AmpApiClientAuthenticationError(msg) from exception
        except (
            aiohttp.ClientError,
            socket.gaierror,
            ConnectionError,
            TimeoutError,
            ValueError,
        ) as exception:
            msg = f"Error fetching instance list - {exception}"
            raise AmpApiClientCommunicationError(msg) from exception

        instances = {
            key: await self._async_get_instance_data(key, instance)
            for key, instance in enumerate(all_instances)
        }
        panel_version = next(
            (
                format_amp_version(instance.amp_version)
                for instance in all_instances
                if instance.module == "ADS" or instance.friendly_name == "ADS"
            ),
            None,
        )
        return AmpCoordinatorData(
            instances=instances,
            panel_version=panel_version,
            panel_update=await self._async_get_panel_update(),
        )

    async def _async_get_panel_update(self) -> AmpPanelUpdate | None:
        """Fetch AMP panel update availability; None if it cannot be determined."""
        try:
            result = await self.core.get_update_info(format_data=True)
        except Exception:  # noqa: BLE001 - purely informational, never fail the refresh
            _LOGGER.debug("Could not fetch AMP panel update info", exc_info=True)
            return None
        if not isinstance(result, UpdateInfo):
            return None
        return AmpPanelUpdate(
            update_available=result.update_available,
            version=result.version or None,
            release_notes_url=result.release_notes_url or None,
        )

    async def _async_get_instance_data(
        self, key: int, instance: Instance
    ) -> AmpExtendedInstance:
        """Build the data for a single instance.

        get_instances() already includes state, metrics and endpoints for every
        instance; only the player list requires a live API call, which AMP
        rejects with "instance not available" unless the instance is running.
        """
        metrics = instance.metrics
        data = AmpExtendedInstance(
            instance_name=instance.friendly_name,
            instance_index=key,
            amp_instance_name=instance.instance_name,
            active_users=(
                metrics.active_users.get("raw_value", 0)
                if metrics and metrics.active_users
                else 0
            ),
            players=None,
            max_active_users=(
                metrics.active_users.get("max_value", 0)
                if metrics and metrics.active_users
                else 0
            ),
            cpu_usage_percentage=(
                metrics.cpu_usage.get("raw_value", 0)
                if metrics and metrics.cpu_usage
                else 0
            ),
            memory_usage_mb=(
                metrics.memory_usage.get("raw_value", 0)
                if metrics and metrics.memory_usage
                else 0
            ),
            # AMP reports app_state "undefined" (-1) for instances that are not
            # running; "stopped" matches what AMP's own UI shows.
            app_state=instance.app_state.name if instance.running else "stopped",
            address=(
                instance.application_endpoints[0]["endpoint"]
                if instance.application_endpoints
                else None
            ),
            running=instance.running,
            amp_version=format_amp_version(instance.amp_version),
        )

        if not instance.running:
            return data

        try:
            players_raw = (await AMPInstance(instance).get_user_list()).sorted
        except ConnectionError:
            # Expected while an instance is starting/installing: the instance
            # is up but its application cannot answer user-list calls yet.
            _LOGGER.debug(
                "Instance %s is not ready to report a player list",
                instance.friendly_name,
            )
            return data
        except Exception:  # noqa: BLE001 - one bad instance must not fail the refresh
            _LOGGER.warning(
                "Could not fetch the player list for instance %s;"
                " reporting it without player data",
                instance.friendly_name,
                exc_info=True,
            )
            return data

        if players_raw:
            data.players = ", ".join(player.name for player in players_raw)
        return data
