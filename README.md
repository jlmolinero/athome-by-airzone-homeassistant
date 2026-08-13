# AtHome by Airzone for Home Assistant

Custom Home Assistant integration for AtHome by Airzone blinds and shutters.

This integration discovers AtHome/Airzone blind components, creates Home Assistant `cover` entities, and creates `select` entities for slat angle only on blinds that actually support louver/slat control.

> Unofficial project: this repository is not affiliated with or endorsed by Airzone.

## Features

- One `cover` entity per discovered blind/shutter.
- Slat angle `select` entities only for louver-capable blinds.
- Open, close, stop, and set-position support.
- Timing calibration button for calculating open/close travel times.
- Uses the AtHome web session/API directly from Home Assistant; no Playwright browser is required inside Home Assistant OS for normal control.

## Installation

### HACS custom repository

Once this repository is public, add it in HACS as a custom repository:

1. HACS → Integrations → three-dot menu → Custom repositories.
2. Repository: this GitHub repository URL.
3. Category: Integration.
4. Install `AtHome by Airzone`.
5. Restart Home Assistant.

### Manual installation

Copy this folder:

```text
custom_components/athome_persianas
```

into your Home Assistant config directory:

```text
/config/custom_components/athome_persianas
```

Then restart Home Assistant.

## Configuration

Add the integration from Home Assistant UI:

```text
Settings → Devices & services → Add integration → AtHome by Airzone
```

The integration asks for:

- script path, usually `/config/custom_components/athome_persianas/athome_persianas.py`
- AtHome email/password, or a `session.json` file as described below
- AtHome web/auth base URLs

## `session.json`

For Home Assistant OS, the recommended runtime path is a local `session.json` file in the integration directory:

```text
/config/custom_components/athome_persianas/session.json
```

Copy `custom_components/athome_persianas/session.example.json` to `session.json` and fill it with the fields from `localStorage['Zhome.session']` in the AtHome web portal.

Minimum expected fields:

```json
{
  "email": "your_email@example.com",
  "authentication_token": "REDACTED",
  "user_id": "REDACTED",
  "device_id": "REDACTED"
}
```

Do **not** commit or share `session.json`. It contains a live session token.

## Timing calibration

The integration stores calibrated travel timings in:

```text
/config/custom_components/athome_persianas/blind_timings.json
```

This file is generated at runtime and should not be committed. Use the `Calibrate timings` button created by the integration to measure all blind open/close travel times.

## Slat/louver support

The integration only creates slat angle selects for blinds whose data reports slat support. Simple open/close shutters do not get `select.*_slats` entities.

## Development safety

Before publishing or opening an issue, make sure these files are never committed:

- `session.json`
- `blind_timings.json`
- `__pycache__/`
- `*.pyc`

## License

MIT
