"""AMP API Client."""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass

import aiohttp
from ampapi import ADSModule, AMPInstance, Bridge
from ampapi.dataclass import APIParams, Instance

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
    """Base instance class for AMP."""

    instance_name: str
    instance_index: int


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
            )
            for index, instance in enumerate(instances)
        ]

    async def async_get_data(self) -> dict[int, AmpExtendedInstance]:
        """Get data from the API for every instance.

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

        return {
            key: await self._async_get_instance_data(key, instance)
            for key, instance in enumerate(all_instances)
        }

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
            app_state=instance.app_state.name,
            address=(
                instance.application_endpoints[0]["endpoint"]
                if instance.application_endpoints
                else None
            ),
            running=instance.running,
        )

        if not instance.running:
            return data

        try:
            players_raw = (await AMPInstance(instance).get_user_list()).sorted
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
