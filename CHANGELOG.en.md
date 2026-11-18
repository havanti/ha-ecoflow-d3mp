# Changelog

All notable changes to this integration. German version: [CHANGELOG.md](CHANGELOG.md).

## 0.1.2

### Changed

- The cell temperature of the built-in pack is enabled by default, like the extra battery's.
  Existing installations keep their setting.
- A Bluetooth disconnect the integration asked for, for example when it is reloaded, is no
  longer logged as a warning. An unexpected one still is.

## 0.1.1

### Fixed

- The extra battery is reliably linked to its station when it is first created. The station
  is now looked up in the integration's own config entry, even before the entity is
  registered.
- A station missing from the device registry is reported as a warning in the log instead of
  the link being dropped silently.
- Detecting how Home Assistant links a device to its parent no longer depends on type
  annotations.

## 0.1.0

First release. Hard fork of `rabits/ha-ef-ble` v1.3.1, reduced to the EcoFlow DELTA 3 Max
Plus and its extra battery.

### Changed from ha-ef-ble

- New domain `ecoflow_d3mp`. Entries from `ha-ef-ble` are not carried over; the device has
  to be set up again.
- Only the DELTA 3 Max Plus is supported. All other devices, the Wave climate platform and
  the packet collection for unsupported devices are removed.
- Entity keys are cleaned up, unique IDs read `d3mp_{serial}_{key}`.
- Translations: English and German.

### Added

- Extra battery as its own device: state of charge, capacity (design, full, remaining),
  cell voltages, temperatures, charging state, type and current. The device does not report
  the current; it is measured from the change in remaining capacity over a minute (charging
  reads positive). A second port is read, but it is unverified and disabled by default.
- Switches for the second AC group, X-Boost, the beeper and "restore outputs after power
  loss". Selection of the AC charging mode.
- Numbers for the standby timers, the screen timeout and the screen brightness.
- Readings: fast charging, run state, outage reserve per output, error codes per subsystem,
  charging state of the system and of the built-in pack, WiFi signal strength.
- The backup reserve reads its state from the field the device actually sets, and always
  sends the level along when it is armed.

### Limits

- Setters stay inside the range EcoFlow offers for this model: charge limit 50–100 %,
  discharge limit 0–30 %, reserve up to 50 % and five points above the discharge limit, AC
  charging power 200–2400 W, DC input current 4–8 A.
- Power off, "disable grid bypass" and the DC input current are disabled by default. Power
  off logs a warning when power is flowing, because the device ignores the command then.

### Removed

- The switches for the energy strategies and for the USB outputs, and the sensors for the
  fan and the battery power: the device does not report the values behind them or does not
  react to the command.
