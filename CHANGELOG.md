# Changelog

## 1.3.1 (2026-07-07)

### Changed

- Maintainership transferred to @sirjmann92 (fork of the inactive
  Samywamy10/ha-cubecoders-amp): `codeowners`, `documentation`, and
  `issue_tracker` in the manifest now point to this fork, and the README
  documents the current feature set. No functional changes.

## 1.3.0 (2026-07-07)

### Added

- **AMP Panel update entity.** A new "AMP Panel" device with a Home Assistant
  `update` entity showing the installed AMP version (from the ADS controller)
  and, via `Core/GetUpdateInfo`, whether a newer AMP version is available —
  including a release-notes link. Appears in Settings → Updates when an AMP
  upgrade is pending. Display-only; installing from HA is intentionally not
  supported. Update-info failures never affect the rest of the refresh.
- **AMP Version diagnostic sensor** per instance, from the instance's
  `amp_version` field.

### Changed

- Stopped instances now report app state `stopped` instead of `undefined`
  (AMP returns state -1 for non-running instances; "stopped" matches AMP's own
  UI).
- The "instance not ready to report a player list" case (e.g. while an
  application is starting or installing) is now logged at debug level without
  a traceback; unexpected per-instance errors still log a warning.
- Coordinator data is now a structured object (`AmpCoordinatorData`) carrying
  per-instance data plus panel-level version/update info.

## 1.2.0 (2026-07-07)

### Added

- **Instance control.** Each instance now gets a switch entity that starts and
  stops it through the ADS controller (`ADSModule/StartInstance` /
  `StopInstance`), which works on stopped instances — so automations can spin
  servers up on demand. The switch state follows the `running` field from the
  coordinator and updates optimistically when toggled.
- **Restart button** per instance (only available while the instance is
  running).
- If AMP refuses an action (`ActionResult.status = False`), the reason is
  surfaced as a Home Assistant error instead of silently ignored.

### Changed

- Per-instance data now carries the real AMP `instance_name` alongside the
  friendly name, since control endpoints require the former. Entity unique IDs
  are unchanged.
- Sensor/switch/button share a common per-instance entity base
  (`AmpInstanceEntity`) and device-info builder.

### Notes

- The switch controls the **instance** (the AMP-managed process), not the game
  application inside it. If the instance is not configured to auto-start its
  application, starting the instance brings up AMP's management layer but not
  the game server itself (configure "Start on instance startup" in AMP's
  instance settings for full spin-up).

## 1.1.0 (2026-07-07)

### Fixed

- **Stopped instances no longer break the whole integration.** The data update
  previously called `get_user_list()` on every instance unconditionally; AMP
  rejects that call for stopped instances ("The requested instance is not
  available at this time"), which failed the entire coordinator refresh and
  took down every sensor. Instance state, metrics, and endpoints are now read
  from the `get_instances()` payload (which is available for stopped instances
  too), and the live player-list call is only made for running instances.
  Stopped instances report their real `app_state` (e.g. `stopped`) instead of
  erroring.
- **One bad instance can no longer fail the refresh.** Any unexpected error
  while fetching a single instance's player list is logged and that instance
  degrades to the baseline `get_instances()` data; all other instances update
  normally.
- **Host URL validation.** Newer aiohttp raises `NonHttpUrlClientError` for
  schemeless URLs. The config flow now requires the host to be a full URL
  including `http://` or `https://` and shows a clear validation error
  otherwise (no scheme is auto-assumed, since many panels are behind an https
  reverse proxy). Trailing slashes and whitespace are stripped.
- **Config flow actually validates.** Setting up (or reconfiguring) the
  integration now performs a real login/`get_instances()` call against the
  panel, so wrong credentials or an unreachable host are reported in the form
  instead of creating a broken entry.
- Sensors handle a missing instance in coordinator data by becoming
  unavailable instead of raising `KeyError`.
- Removed leftover integration-blueprint dead code that called
  `jsonplaceholder.typicode.com`.

### Added

- **Reconfigure support.** The integration can now be reconfigured from the
  integration page (host/username/password) without deleting and re-adding it.
- `translations/en.json` so config-flow labels and errors render properly
  (custom integrations do not resolve `strings.json` common-key references).
- New `running` field on the per-instance data.

### Changed

- The coordinator is now created with an explicit `config_entry` (implicit
  lookup is deprecated in recent Home Assistant versions).
- Version bumped to 1.1.0 in `manifest.json`.
