# Olight for Home Assistant (unofficial)

**Your Olight Ostation 2 Pro as a real Home Assistant device** — every bay, every cell, locally.
No cloud, no vendor app running in the background.

[![tests](https://github.com/seanmarpo/ha-olight/actions/workflows/test.yml/badge.svg)](https://github.com/seanmarpo/ha-olight/actions/workflows/test.yml)

| | |
|---|---|
| 🔋 **Per-cell telemetry** | charge %, voltage, current, chemistry, elapsed time — for each of the four bays |
| 🧭 **Bays as sub-devices** | AA1, AA2, AAA1, AAA2 each appear as their own device under the station |
| 🏠 **Fully local** | Tuya protocol 3.5 over your LAN; the station never has to reach the internet |
| 🤖 **Automatable** | notify when a cell finishes, when the reject bin fills, or pause charging off-peak |

> ⚠️ Independent, unofficial project. Not affiliated with Olight or Tuya. It interoperates with
> **your own** device on **your own** network. It may break if Olight changes the firmware.

## What you get

**The station** — charging on/off, quiet-hours toggle and window (start/end), wake sensitivity, cells charged, cells
rejected, and three fill warnings (rejected bin, AA compartment, AAA compartment).

**Each bay, as its own device** — battery present, charging, charge %, voltage, current,
chemistry (Ni-MH / Li-ion / detecting), elapsed charging time and the still-unexplained byte 12.

## Requirements

- An **Ostation 2 Pro** on your Wi-Fi. The station needs **2.4 GHz** — it will not join a 5 GHz
  network, and it does not support Wi-Fi Direct.
- Its Tuya **device ID** and **local key** (below).
- A static IP or DHCP reservation for the station is strongly recommended.

## Getting the device ID and local key

The station speaks a standard, documented protocol — but Tuya encrypts the LAN session with a
16-character key that is unique to your unit. You need it (and the 22-character device id) **once**;
after that everything is on your LAN and you can block the station from the internet.

The controlling app is the ordinary **Olight** app (`com.olight.omall`) — there is no separate
"Osite" app — and it is built on the Tuya SDK, which caches the key **encrypted, per device** and
only decrypts it at runtime. So there is no purely-static shortcut; the fully local way to read it
is to run the app once and read the key from Android's log.

**Fully local (recommended):** an Android **emulator** on your own machine — no phone, no cloud.
One script does the whole thing (SDK, emulator, app install, log capture) on macOS or Linux:

```bash
./tools/extract_key.sh
```

It boots the emulator, installs the Olight app and then waits on the log; the only thing you do is
sign into the account your station is paired to, in the emulator window. When the key appears it is
printed and saved to `tools/ostation-key.env`. Step-by-step and the manual equivalent in
**[docs/GET-LOCAL-KEY.md](docs/GET-LOCAL-KEY.md)**. No root, no Frida. (A borrowed Android phone
works identically with the one `adb logcat` line in that doc.)

**Check the key before touching Home Assistant:**

```bash
python3 tools/probe.py --host <ip> --id <device id> --key <local key>     # one read
python3 tools/probe.py ... --watch                                         # live, on change
```

It prints every raw datapoint and the decoded state of all four bays, using the exact decoder the
integration ships. Keep its output when reporting anything — the raw DP110 is what confirms the
payload layout on your firmware.

**Phone only, one-time cloud lookup:** no emulator, no Android — a Tuya developer project, one QR
scan, and [`tools/get_local_key.py`](tools/get_local_key.py). Step-by-step in
**[docs/GET-LOCAL-KEY-CLOUD.md](docs/GET-LOCAL-KEY-CLOUD.md)**. Runtime stays fully local either
way — this only affects how you obtain the key the first time.

> **Paired the station "without an account"?** Then the Olight app is holding it under an
> anonymous Tuya account nobody else can sign into, so the emulator route is closed to you — and
> there is nothing to lose by re-pairing it with Smart Life, which makes the cloud lookup the
> documented, reliable path. The doc above covers exactly this.

See **[docs/REVERSE-ENGINEERING.md](docs/REVERSE-ENGINEERING.md)** for how all of this was
established (the app is a Tuya app, the key is cloud-issued and pinned, etc.).

## Install

Requires **Home Assistant 2026.8 or newer** (tested on 2026.11).

**HACS** → Custom repositories → add `https://github.com/seanmarpo/ha-olight` as an
Integration → install → restart Home Assistant.

**Manually** → copy `custom_components/olight` into your `config/custom_components/` → restart.

Then **Settings → Devices & Services → Add Integration → Olight**, and enter the station's IP,
device ID and local key.

**If the key or IP changes later** (re-pairing or a factory reset makes Tuya issue a new key; DHCP
can move the address), open the station's entry and choose **Reconfigure** — the device and its
history stay intact. There is no need to delete and re-add.

## One connection at a time

The station accepts a **single local connection**. While Home Assistant is polling it, the Olight
app will not connect — and if you open the Olight app, Home Assistant is dropped until its next poll. This
is a limitation of the station, not of this integration. The integration holds one persistent
socket and polls every 15 seconds rather than reconnecting each time, which keeps the handshake
cost down and the connection stable.

## Known rough edges

- **Byte 12** of each bay record is unmapped. The community first read it as a temperature (~25
  at rest), but it is reported near 100 during a fast charge and appears to track the *other*
  bay's activity, and the upstream tuya-local config leaves it unknown. It is exposed raw, as a
  unitless diagnostic, until someone establishes what it is. Bytes 5–7 and 13–16 are zero for
  Ni-MH and reportedly carry something for Li-ion; they are not decoded yet.
- **DP113** has no known meaning and has only ever been seen at 0. It is exposed as a diagnostic
  sensor so its behaviour can be observed; if you work out what it does, please open an issue.
- A cell keeps reporting a **ghost voltage** for a short while after you pull it. Voltage dropping
  to exactly 0 mV is the reliable "bay is empty" signal, and that is what `Battery present` uses.
- Detection takes about **3 minutes** of probing before charging starts.

## Other Olight devices

**Sphere ambient lights** are BLE SIG Mesh behind a Tuya Bluetooth gateway, and are already
supported upstream by [tuya-local](https://github.com/make-all/tuya-local)
(`olight_sphere_light.yaml`, product id `d0dpga0h`). Use that rather than this integration — there
is no reason to reimplement a config someone already merged. You will need a Tuya BT gateway, and
the Sphere must be paired through the Olight app first.

## Protocol notes

The station is a Tuya protocol 3.5 device (product ids seen so far: `1fnensm6`, `v8znljza`,
`rcj4z3pdmhkzflio`). It closes an idle socket, so the client sends a heartbeat every 8 s on the
persistent connection. Its datapoints:

| DP | Type | Meaning |
|---|---|---|
| 101 | bool | charging enabled |
| 102 | int | cells fully charged |
| 103 | bool | rejected-battery bin full |
| 104 | bool | AA compartment full |
| 105 | int | wake sensitivity (1–5) |
| 106 | bool | AAA compartment full |
| 108 | int | cells rejected |
| 110 | raw | per-bay telemetry (below) |
| 111 | bool | quiet hours enabled |
| 112 | raw | quiet-hours window: `[start h, start m, end h, end m]`, base64 |
| 113 | int | unknown, always 0 so far |

**DP110** is 68 bytes, sent base64-encoded: four 17-byte records, one per bay, in the order AA1,
AA2, AAA1, AAA2. Each record carries its own bay id, so this integration keys off that rather than
the record's position. Layout agrees with the upstream tuya-local config.

```
offset  0     1      2     3   4    5-7   8-9      10-11      12    13-16
field   slot  chem   SoC%  h   min  ?     mV (BE)  mA÷10 (BE) ?     ?
              00 detecting
              01 Ni-MH
              02 Li-ion
```

> The DP110 dump published in [tuya-local issue #6069](https://github.com/make-all/tuya-local/issues/6069)
> is 65 bytes rather than 68 — zero bytes were lost in transcription, and only its first record is
> intact. That record is what independently confirms this layout: `0578` → 1400 mV and `19` → 25 °C
> are both exactly right for a charged Ni-MH cell at room temperature. The decoder resynchronises
> on record headers and drops any record whose values are physically impossible, so a malformed or
> revised payload degrades to fewer bays instead of inventing readings.

## Credits

The datapoint map and the initial DP110 analysis come from the Home Assistant community thread
[Integrating the Olight Ostation 2 in Home Assistant](https://community.home-assistant.io/t/integrating-the-olight-ostation-2-in-home-assistant-guide/1004530)
and tuya-local issue #6069. This project turns that work into a first-class integration with
per-bay devices and a hardened decoder.

## Licence

MIT.
