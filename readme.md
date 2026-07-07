# Cubecoders AMP HA Integration

Integrates with [AMP](https://cubecoders.com/AMP) to create a device for each game server instance, with sensors, start/stop controls, and update info.

Maintained by [@sirjmann92](https://github.com/sirjmann92). Originally created by [@samywamy10](https://github.com/Samywamy10/ha-cubecoders-amp); this fork continues development since the original repository became inactive.

## Features

Per instance (device):
- **Switch** to start/stop the instance via the ADS controller — works on stopped instances, so automations can spin servers up on demand
- **Restart button** (available while the instance is running)
- Sensors: app state, active users, max users, player list, CPU %, memory usage, address, AMP version
- Stopped instances stay visible in HA (state `stopped`) instead of breaking the integration

Panel-wide:
- **AMP Panel device** with an update entity showing the installed AMP version and whether a newer AMP release is available (appears in Settings → Updates)

## Installing

Install via [HACS by adding a custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) (`sirjmann92/ha-cubecoders-amp`, category *Integration*). Then search `Cubecoders AMP` in HACS, install, restart Home Assistant, and add the `AMP` integration.

### Configuration options

| Property | Example |
| ------- | ------- |
| host | `http://192.168.86.194:8080` or `https://amp.example.com` — must be a full URL including `http://` or `https://` |
| username | `<yourAmpAdminUsername>` |
| password | `<yourAmpAdminPassword>` |

The integration supports reconfiguration from the integration page (no need to delete and re-add to change host or credentials).

## Dependencies

Relies on [cc-ampapi](https://github.com/k8thekat/AMPAPI_Python)
