# CHANGELOG.md — Audyssey REW Tuner Project Log

> Reverse-engineering and implementation log. Newest entries at top.

---

## 2026-04-26

### 🔧 FL Pilot Tooling (Branch — DISCARDED)

A branch was started for front-left (FL) pilot tooling to develop the full REW+UMIK measurement workflow in isolation before scaling to all 11 channels.

- **Branch:** `fl-pilot-tooling`
- **Status:** ❌ Discarded — absorbed into main Epic 1 plan
- **Reason:** The tooling complexity was underestimated. A better approach was adopted: full Epic 1 with all 10 stories tracked in PLAN.md, per-speaker workflow documented, and direct integration into Echo Console UI rather than isolated tooling.

---

### 📋 Full REW+UMIK Calibration System Planned

Epic 1 formally kicked off — a complete measurement → EQ → transfer pipeline using REW, a UMIK microphone, and the Denon X3800H binary protocol.

- **Stories:** 10 total (Stories 1-10 in PLAN.md)
- **Per-speaker workflow:** FL, C, FR, SBR, SBL, FHL, FHR, SW1, SW2, FDL, FDR
- **UMIK:** UMIK-1 from Cross Spectrum Labs (Serial: [REDACTED], dated 2023-09-02)
- **Rew workflow:** REW API sweeps → curve retrieval → match-target → PEQ generation → binary transfer
- **Current focus:** Stories 1-3 (UMIK calibration import, REW sweep control, measurement retrieval)
- **Outstanding:** UMIK cal import to REW not yet automated; target curve UI not built; distances from IR not implemented

---

## 2026-04-25

### 🎛️ Echo Console AVR Tools Tab Built

Added a complete **AVR Tools tab** to the Echo Console at `http://192.168.41.108:18790`. The tab provides:

- **Preset switching** — Preset 1 / Preset 2 via Telnet (MSSV command)
- **Power controls** — Power Off / Power On / Power Cycle via Python subprocess
- **OCA file listing** — lists `.oca` files in the workspace with timestamps
- **OCA transfer** — transfers selected calibration to AVR via binary protocol
- **LPF / Bass Mode** — sets subwoofer low-pass filter and bass mode via Python

**Key commit:** `d6a343d` — switch-preset + power-cycle from UI

**Power cycle implementation:**
- Uses `avr_telnet.py --power-cycle` which calls Python subprocess
- Confirmed working: `power-cycle` sends `POFF` → waits 30s → sends `PWON`
- Warning added before power cycle action (aa518fd)

**Power cycle warning commit:** `aa518fd`

---

### 🔄 AVRTelnet Class Unified

Refactored the Telnet AVR control into a single `AVRTelnet` class in `avr_telnet.py`:
- Unified `connect()`, `send_command()`, `close()` methods
- Added `--power-cycle` flag as a top-level action
- Separated raw TCP binary protocol handling from Telnet ASCII commands

---

### 📡 Telnet Commands Verified

Confirmed the following Telnet commands work on the Denon X3800H (port 23):
| Command | Purpose | Verified |
|---------|--------|----------|
| `MSSV<ch>=<freq>Hz,<gain>dB,Q=<q>` | Set PEQ filter | ✅ |
| `MSD<ch><distance_mm>` | Set distance in mm | ✅ |
| `MST<ch><trim_x10>` | Set trim in 0.1 dB steps | ✅ |
| `POFF` | Standby | ✅ |
| `PWON` | Wake | ✅ |
| `ZM?` | Cycle Audyssey presets | ✅ |
| `MSSV?<ch>` | Query filter | ✅ |

---

### 🗂️ TCX.oca Set as Preset 2 Mapping

`TCX.oca` (calibration run from the car's tech ceiling experiment) officially designated as **Preset 2** on the X3800H.

- Preset 1: remains reserved for A1 Evo factory calibration
- Preset 2: TCX.oca, transferable via `oca_transfer.py --preset 2`
- Both presets can be swapped via `ZM?` on the AVR or via Echo Console UI

---

## 2026-04-24

### 📦 Binary Protocol Fully Reverse-Engineered

After multiple iterations and packet captures, the full binary protocol on **port 1256** was confirmed:

**Message types:**
- `GET_AVRINF` — Query AVR capabilities (CoefWaitTime, EQType)
- `SET_SETDAT` — Configuration (distances, trims, crossovers)
- `SET_COEFDT` — Filter coefficients (126 × float32 LE per message)

**Key findings locked in:**
- Port 1256 = **raw TCP** (not Telnet)
- Marker byte: `0x54` ('T')
- Counter: 3 bytes little-endian, base `0x1300`
- Coefficient offset: **TCP payload offset 22** (not 24)
- Float encoding: **little-endian** IEEE 754 float32
- Meta field for SET_COEFDT: `02 00 01 00`
- SR codes: 0=32kHz, 52=44.1kHz, 57=48kHz, 184=96kHz

**Pcaps captured:**
- `acoustix_transfer_1777065760128..pcapng` — full transfer from A1 Evo binary
- `acoustix_transfer_getavrconfig_1777012089418..pcapng` — GET_AVRINF response

**Key verification:** OCA filter[0] LE bytes `9cd1fd3e` found at TCP offset 22 in retransmitted blocks, matching OCA FL filter[0] value of 0.495740.

---

### 🔄 OCA Transfer Working End-to-End

`oca_transfer.py` successfully transferred a full calibration (`.oca` file) to the Denon X3800H via binary protocol:

**Verified results after power cycle:**
- FL: -0.5dB trim, 2.75m distance ✅
- SW1: -0.5dB trim, 2.81m distance ✅
- SW2: -2.5dB trim, 2.82m distance ✅

**Process:**
1. Load `.oca` calibration file
2. Extract config bytes from matching `.pcapng` (or build from scratch)
3. Connect to port 1256 (raw TCP)
4. Send GET_AVRINF → read CoefWaitTime (15000ms)
5. Send SET_SETDAT for all channels
6. Wait CoefWaitTime
7. Send SET_COEFDT for all channels at all SRs
8. Power cycle AVR to apply

---

## Earlier History

See `SPEC.md` for earlier protocol discovery iterations and `README.md` for the OCA file inventory.

---

*Log started: 2026-04-24*  
*Last updated: 2026-04-26*