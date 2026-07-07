# Cubecoders AMP HA Integration

Integrates with [AMP](https://cubecoders.com/AMP) to create a device for each game server instance, with sensors, start/stop controls, player events, console commands, and update info.

Maintained by [@sirjmann92](https://github.com/sirjmann92). Originally created by [@samywamy10](https://github.com/Samywamy10/ha-cubecoders-amp); this fork continues development since the original repository became inactive.

## Your game servers, everywhere Home Assistant is

Once your AMP panel is in Home Assistant, your game servers stop being something you manage from a browser tab and start being part of your smart home. Expose the entities to Alexa, Google Home, or HA's own Assist, and suddenly:

- 🗣️ *"Alexa, turn on Palworld"* — spins up the instance on demand
- 🗣️ *"Hey Google, restart Enshrouded"* — one voice command instead of logging into the panel
- 🗣️ *"Alexa, update Minecraft"* — kicks off a SteamCMD game update
- ⚡ *"Computer, smite AnnoyingPlayer12"* — yes, there's a lightning-bolt service for Minecraft

And because everything is entities and events, automations get fun fast:

- 📱 Get a phone notification when a friend joins your server
- 💤 **Self-stopping servers**: instance empty for 30 minutes → announce a shutdown in chat → save → stop the instance (no more paying the idle-RAM tax on servers nobody's playing)
- 🌙 Nightly maintenance: announce → `save-all` → back up → update the game server → restart, all while nobody's online
- 💡 Flash a light when someone joins, put player counts on a dashboard, whatever you can dream up

## Features

Per instance (device):
- **Instance switch** — start/stop the instance via the ADS controller (works on stopped instances, so automations can spin servers up on demand)
- **Application switch** — start/stop the game server inside a running instance
- **Buttons** — Restart Instance, Restart Application, Update Game Server (SteamCMD/app update)
- **Sensors** — app state, active users, max users, player list, CPU %, memory usage, uptime, address, AMP version, and **Empty Since** (timestamp of when the last player left — ideal for auto-shutdown automations)
- Stopped instances stay visible in HA (state `stopped`) instead of breaking the integration

Panel-wide:
- **AMP Panel device** with an update entity showing the installed AMP version and whether a newer AMP release is available (appears in Settings → Updates)

Events (on the HA event bus, fired on each poll):
- `cubecoders_player_joined` / `cubecoders_player_left` with `instance_name`, `amp_instance_name`, and `player` — trigger automations on players coming and going

Services (`Developer tools → Actions`):
- `cubecoders.send_command` — send any console command to a running instance (announcements, `save-all`, anything)
- Minecraft player management (instance + player name, no UUIDs needed):
  `cubecoders.mc_kick_player`, `mc_ban_player`, `mc_smite_player`, `mc_whitelist_add`, `mc_whitelist_remove`, `mc_op_player`, `mc_deop_player`

### Example: auto-stop an empty server

```yaml
automation:
  - alias: "Stop Palworld when empty for 30 minutes"
    triggers:
      - trigger: template
        value_template: >-
          {{ states('sensor.silverscruff_s_palworld_empty_since') not in ('unknown', 'unavailable')
             and now() - states('sensor.silverscruff_s_palworld_empty_since') | as_datetime > timedelta(minutes=30) }}
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.silverscruff_s_palworld_instance
```

### Example: notify when a friend joins

```yaml
automation:
  - alias: "Someone joined a game server"
    triggers:
      - trigger: event
        event_type: cubecoders_player_joined
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: "{{ trigger.event.data.player }} joined {{ trigger.event.data.instance_name }}"
```

## Installing

Install via [HACS by adding a custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) (`sirjmann92/ha-cubecoders-amp`, category *Integration*). Then search `Cubecoders AMP` in HACS, install, restart Home Assistant, and add the `AMP` integration.

### Configuration options

| Property | Example |
| ------- | ------- |
| host | `http://192.168.86.194:8080` or `https://amp.example.com` — must be a full URL including `http://` or `https://` |
| username | `<yourAmpAdminUsername>` |
| password | `<yourAmpAdminPassword>` |

The integration supports reconfiguration from the integration page (no need to delete and re-add to change host or credentials).

### Notes

- The **Instance** switch controls AMP's managed process; the **Application** switch controls the game server inside it. If your instance is configured to auto-start its application, the Instance switch alone gives you full one-toggle spin-up.
- Services accept the instance's friendly name or AMP instance name, case-insensitively — voice-assistant friendly.
- Kick/ban/smite require the player to be currently online (their UUID is resolved from the live player list); whitelist and op/de-op work for offline players too.

## Dependencies

Relies on [cc-ampapi](https://github.com/k8thekat/AMPAPI_Python)
