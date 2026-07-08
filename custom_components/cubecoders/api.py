"""AMP API Client."""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - used in dataclass field annotation

import aiohttp
from ampapi import ADSModule, AMPInstance, Bridge, Core
from ampapi.dataclass import (
    ActionResult,
    APIParams,
    Instance,
    UpdateInfo,
    Updates,
    VersionInfo,
)
from ampapi.instance import AMPMinecraftInstance

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
    module: str
    player_list: list[str] = field(default_factory=list)
    uptime: str | None = None
    # Set by the coordinator, which compares consecutive refreshes.
    empty_since: datetime | None = None


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


def join_version_build(version: str | None, build: str | None) -> str | None:
    """Combine a version string with its build number.

    AMP patches bump only the build (e.g. 20260625.1 -> 20260625.2) while the
    version string stays the same, so the build must be part of any
    installed-vs-latest comparison.
    """
    if not version:
        return None
    return f"{version} ({build})" if build else version


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

    async def async_upgrade_instance(self, amp_instance_name: str) -> None:
        """Update the game server (SteamCMD/app update) via the ADS controller."""
        await self._async_instance_action("upgrade", amp_instance_name)

    async def _async_instance_action(self, action: str, amp_instance_name: str) -> None:
        """Run an ADS-level start/stop/restart/upgrade action on an instance."""
        await self._async_call(
            getattr(self.ads, f"{action}_instance")(
                instance_name=amp_instance_name, format_data=True
            ),
            action=f"{action} instance",
            target=amp_instance_name,
        )

    async def async_start_application(self, instance_name: str) -> None:
        """Start the application (game server) inside a running instance."""
        live_instance = await self._async_get_live_instance(instance_name)
        await self._async_call(
            live_instance.start_application(format_data=True),
            action="start application",
            target=instance_name,
        )

    async def async_stop_application(self, instance_name: str) -> None:
        """Stop the application (game server) inside a running instance."""
        live_instance = await self._async_get_live_instance(instance_name)
        await self._async_call(
            live_instance.stop_application(),
            action="stop application",
            target=instance_name,
        )

    async def async_restart_application(self, instance_name: str) -> None:
        """Restart the application (game server) inside a running instance."""
        live_instance = await self._async_get_live_instance(instance_name)
        await self._async_call(
            live_instance.restart_application(format_data=True),
            action="restart application",
            target=instance_name,
        )

    async def async_send_console_command(self, instance_name: str, command: str) -> None:
        """Send a console command/message to a running instance's application."""
        live_instance = await self._async_get_live_instance(instance_name)
        await self._async_call(
            live_instance.send_console_message(command),
            action="send console command",
            target=instance_name,
        )

    # Minecraft actions that require the player's full UUID; resolved from the
    # live player list so callers can pass a plain player name.
    _MC_UUID_ACTIONS = {
        "kick": "mc_kick_user_by_id",
        "ban": "mc_ban_user_by_id",
        "smite": "mc_smite_by_id",
    }
    # Minecraft actions that accept a player name (or UUID) directly.
    _MC_NAME_ACTIONS = {
        "whitelist_add": "mc_add_to_whitelist",
        "whitelist_remove": "mc_remove_whitelist_entry",
        "op": "mc_add_op_entry",
        "deop": "mc_remove_op_entry",
    }

    async def async_mc_player_action(
        self, instance_name: str, action: str, player: str
    ) -> None:
        """Run a Minecraft player action (kick/ban/smite/whitelist/op) on an instance."""
        live_instance = await self._async_get_live_instance(instance_name)
        if not isinstance(live_instance, AMPMinecraftInstance):
            msg = f"Instance '{instance_name}' is not a Minecraft instance"
            raise AmpApiClientError(msg)

        if action in self._MC_UUID_ACTIONS:
            players = (
                await self._async_call(
                    live_instance.get_user_list(),
                    action="list players",
                    target=instance_name,
                )
            ).sorted
            match = next(
                (p for p in players if p.name.lower() == player.lower()), None
            )
            if match is None:
                msg = f"Player '{player}' is not online on '{instance_name}'"
                raise AmpApiClientError(msg)
            method = getattr(live_instance, self._MC_UUID_ACTIONS[action])
            await self._async_call(
                method(match.uuid), action=action, target=instance_name
            )
        elif action in self._MC_NAME_ACTIONS:
            method = getattr(live_instance, self._MC_NAME_ACTIONS[action])
            await self._async_call(
                method(player), action=action, target=instance_name
            )
        else:
            msg = f"Unknown Minecraft action '{action}'"
            raise AmpApiClientError(msg)

    async def _async_get_live_instance(self, instance_name: str) -> AMPInstance:
        """Look up a running instance by friendly or AMP name (case-insensitive).

        Returns an AMPMinecraftInstance for Minecraft instances so the mc_*
        endpoints are available.
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

        wanted = instance_name.strip().lower()
        match = next(
            (
                instance
                for instance in all_instances
                if wanted
                in (instance.friendly_name.lower(), instance.instance_name.lower())
            ),
            None,
        )
        if match is None:
            msg = f"No AMP instance named '{instance_name}'"
            raise AmpApiClientError(msg)
        if not match.running:
            msg = f"Instance '{instance_name}' is not running"
            raise AmpApiClientError(msg)
        cls = AMPMinecraftInstance if match.module == "Minecraft" else AMPInstance
        return cls(match)

    async def _async_call(self, coro, action: str, target: str):  # noqa: ANN001, ANN202
        """Await an ampapi call, mapping errors and refused ActionResults."""
        try:
            result = await coro
        except PermissionError as exception:
            msg = f"Authentication failed - {exception}"
            raise AmpApiClientAuthenticationError(msg) from exception
        except RuntimeError as exception:
            # ampapi raises RuntimeError for wrong-module calls (e.g. mc_* on
            # a non-Minecraft instance).
            msg = f"Cannot {action} for {target}: {exception}"
            raise AmpApiClientError(msg) from exception
        except (
            aiohttp.ClientError,
            socket.gaierror,
            ConnectionError,
            TimeoutError,
            ValueError,
        ) as exception:
            msg = f"Failed to {action} for {target} - {exception}"
            raise AmpApiClientCommunicationError(msg) from exception

        if isinstance(result, ActionResult) and result.status is False:
            msg = (
                f"AMP refused to {action} for {target}:"
                f" {result.reason or 'no reason given'}"
            )
            raise AmpApiClientError(msg)
        return result

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
        return AmpCoordinatorData(
            instances=instances,
            panel_version=await self._async_get_panel_version(all_instances),
            panel_update=await self._async_get_panel_update(),
        )

    async def _async_get_panel_version(
        self, all_instances: list[Instance]
    ) -> str | None:
        """Return the panel's running version including its build number.

        Core/GetModuleInfo is the authoritative source because it includes the
        build; the ADS instance's amp_version (version string only) is the
        fallback.
        """
        try:
            module = await self.core.get_module_info(format_data=True)
        except Exception:  # noqa: BLE001 - fall back to the instance list below
            _LOGGER.debug("Could not fetch AMP module info", exc_info=True)
        else:
            version = join_version_build(
                format_amp_version(getattr(module, "amp_version", None)),
                getattr(module, "amp_build", None),
            )
            if version is not None:
                return version

        return next(
            (
                format_amp_version(instance.amp_version)
                for instance in all_instances
                if instance.module == "ADS" or instance.friendly_name == "ADS"
            ),
            None,
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
            # Include the build so patch releases (same version string, new
            # build) compare as different from the installed version.
            version=join_version_build(result.version or None, result.build or None),
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
            module=instance.module,
        )

        if not instance.running:
            return data

        live_instance = AMPInstance(instance)
        try:
            players_raw = (await live_instance.get_user_list()).sorted
        except ConnectionError:
            # Expected while an instance is starting/installing: the instance
            # is up but its application cannot answer user-list calls yet.
            _LOGGER.debug(
                "Instance %s is not ready to report a player list",
                instance.friendly_name,
            )
        except Exception:  # noqa: BLE001 - one bad instance must not fail the refresh
            _LOGGER.warning(
                "Could not fetch the player list for instance %s;"
                " reporting it without player data",
                instance.friendly_name,
                exc_info=True,
            )
        else:
            if players_raw:
                data.player_list = [player.name for player in players_raw]
                data.players = ", ".join(data.player_list)

        try:
            updates = await live_instance.get_updates(format_data=True)
        except Exception:  # noqa: BLE001 - uptime is nice-to-have, never fail on it
            _LOGGER.debug(
                "Could not fetch live status for instance %s",
                instance.friendly_name,
            )
        else:
            if isinstance(updates, Updates) and updates.status is not None:
                data.uptime = updates.status.uptime or None

        return data
