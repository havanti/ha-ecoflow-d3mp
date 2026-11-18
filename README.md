# EcoFlow Delta 3 Max Plus for Home Assistant

Unofficial Home Assistant integration for the **EcoFlow DELTA 3 Max Plus** and its extra
battery, over Bluetooth LE. Local only: no cloud connection is used after setup.

It supports this one model and nothing else. Every reading and command in it is based on
measurements taken on a real unit, and what could not be measured is marked as unverified
and starts disabled.

> [!CAUTION]
> No warranty, use at your own risk. This is not an EcoFlow product and the author is not
> affiliated with EcoFlow. The device stores a lot of energy and switches mains voltage. The
> protocol is reverse engineered, so a firmware update can break the integration.

## What you get

- **Sensors:** state of charge of the system and of the built-in pack, input and output
  power, AC, DC, solar and USB power per port, remaining time, cell temperatures, charging
  state, error codes per subsystem
- **Switches:** both AC output groups, 12 V output, backup reserve, X-Boost, beeper, restore
  outputs after power loss, disable grid bypass (disabled by default)
- **Numbers:** charge limit (50–100 %), discharge limit (0–30 %), backup reserve (up to
  50 %), AC charging power (200–2400 W), standby timers, screen timeout and brightness
- **Select:** AC charging mode
- **Button:** power off (disabled by default)
- **Extra battery:** its own device with state of charge, capacity in Ah, energy in Wh,
  current, cell voltages, temperatures and charging state. Energy is the reported capacity
  at the pack's nominal 51.2 V, and current is measured from the change in remaining
  capacity; the device reports neither directly

## Limits you should know

- **One Bluetooth connection.** The device accepts a single central. While Home Assistant
  is connected, the EcoFlow app cannot reach it over Bluetooth, and the other way round.
- **Firmware versions are not available** over Bluetooth on this model.
- **Power off is one way.** The device only obeys while no power flows in or out, and it
  cannot be switched back on over Bluetooth.
- **Reaching the discharge limit drops every output.** It takes precedence over the backup
  reserve, so the integration keeps the reserve five points above the limit.
- **Unverified, disabled by default:** the second extra battery port, the DC input current
  setting, and the mains outage flag. They are read the way the measured parts suggest and
  have not been confirmed on a device.
- The setters stay inside the range EcoFlow offers for this model. Two advanced options
  lift the lower bound of AC charging power and DC input current; read their warnings first.

## Installation

Requirements: Home Assistant 2024.7 or newer with Bluetooth, and the device bound to your
EcoFlow account in the EcoFlow app.

### HACS

1. In HACS, open the menu and choose **Custom repositories**
2. Add `https://github.com/havanti/ha-ecoflow-d3mp` with category **Integration**
3. Install **EcoFlow Delta 3 Max Plus** and restart Home Assistant

### Manual

Copy `custom_components/ecoflow_d3mp` into the `custom_components` folder of your Home
Assistant configuration and restart.

### Setup

Close the EcoFlow app, then add the integration under **Settings → Devices & services**.
The device is discovered over Bluetooth. You need your EcoFlow user ID; the setup form can
fetch it once with your EcoFlow login.

## Origin and licence

This is a hard fork of [rabits/ha-ef-ble](https://github.com/rabits/ha-ef-ble) at v1.3.1,
reduced to a single device and developed independently since. The Bluetooth protocol work,
the connection handling and the entity framework come from that project and its
contributors. Entities set up with `ha-ef-ble` are not migrated.

Licensed under the [Apache License 2.0](LICENSE), like the original.
