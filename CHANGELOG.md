# Changelog

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
