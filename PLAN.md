# Audyssey REW Tuner — Project Plan

## Epic 1: Full REW + UMIK Calibration System

> Build a complete measurement → EQ → transfer pipeline using REW, a UMIK microphone, and the Denon X3800H binary protocol.

**Start Date:** 2026-04-26  
**Status:** 🟡 In Progress  
**Goal:** Measure all 11 channels with REW + UMIK, generate PEQ filters, transfer to AVR via binary protocol.

---

## Stories

### Story 1 — UMIK Calibration Import
**Status:** 🟡 in-progress  
**Summary:** Load UMIK calibration file (.txt from Cross Spectrum Labs) into REW via API.  
**Owner:** Echo  
**Details:**
- UMIK-1 USB measurement mic with known sensitivity response
- Calibration file from Cross Spectrum Labs (Serial: [REDACTED], dated 2023-09-02)
- Parse the tab-delimited or CSV cal file → apply as REW mic calibration
- Verify via REW API (`POST /eq/calibration/set` or similar)

---

### Story 2 — REW Measurement Control
**Status:** 🟡 in-progress  
**Summary:** Trigger REW to run frequency sweeps for each speaker channel.  
**Owner:** Echo  
**Details:**
- Use REW API (port 4735) to start measurements
- Configurable sweep duration (default 2s exponential chirp)
- Level matching before sweep
- Loop through all 11 channels: FL, C, FR, SBR, SBL, FHL, FHR, SW1, SW2, FDL, FDR
- Store measurement UUIDs per channel for later retrieval

---

### Story 3 — Measurement Data Retrieval
**Status:** 🟡 in-progress  
**Summary:** Fetch measurement curves from REW after each sweep.  
**Owner:** Echo  
**Details:**
- Retrieve `frequency/magnitude` pairs per channel from REW API
- Parse and store in session memory
- Identify modal resonances and target frequency ranges
- Flag channels with problematic peaks/nulls

---

### Story 4 — Target Curve Selection
**Status:** 📋 backlog  
**Summary:** Let user pick a target curve (AcoustiX, Laidback, Flat, etc.) for EQ matching.  
**Owner:** Echo  
**Details:**
- List curves from `target_curves/` directory
- Apply selected curve to each channel in REW
- Target curve defines: crossover freq, max EQ frequency, boost limits
- Curves: `acoustix.txt` (default), `laidback.txt`, `flat.txt`, custom

---

### Story 5 — PEQ Filter Generation
**Status:** 📋 backlog  
**Summary:** Generate PEQ filter parameters (freq, gain, Q) per channel from REW match-target.  
**Owner:** Echo  
**Details:**
- For each channel: call REW `match-target` with measurement curve + target curve
- Extract resulting PEQ filters (up to 6 per channel, typical)
- Convert REW PEQ format → internal `peq[]` array
- Store filters for all 11 channels + subwoofer

---

### Story 6 — Channel Distance & Trim
**Status:** 📋 backlog  
**Summary:** Extract or manually set speaker distances and trims for all channels.  
**Owner:** Echo  
**Details:**
- Read distances from REW measurement (time-of-flight from impulse response)
- Fall back to current AVR values (via Telnet query)
- Trims derived from REW SPL measurements at reference point
- Per-channel: distance in mm, trim in 0.1 dB steps

---

### Story 7 — Binary Protocol Transfer
**Status:** 📋 backlog  
**Summary:** Transfer all config (SET_SETDAT) and coefficients (SET_COEFDT) to X3800H via port 1256.  
**Owner:** Echo  
**Details:**
- Connect to port 1256, send GET_AVRINF, read CoefWaitTime
- Send SET_SETDAT per channel (distances, trims, crossovers)
- Wait CoefWaitTime (typically 15000ms)
- Send SET_COEFDT per channel per sample rate (126 float32 coefficients)
- Handle 3x retry on coefficient sends
- All 4 SRs: 32kHz (0), 44.1kHz (52), 48kHz (57), 96kHz (184)

---

### Story 8 — Preset Management
**Status:** 📋 backlog  
**Summary:** Write calibration to Preset 1 or Preset 2 on X3800H.  
**Owner:** Echo  
**Details:**
- X3800H has two Audyssey preset slots (Preset 1, Preset 2)
- Default: write to Preset 2 (Preset 1 reserved for A1 Evo factory calibration)
- TCX.oca mapped as Preset 2 (confirmed 2026-04-25)
- Verify preset via Telnet query after transfer

---

### Story 9 — Apply & Verify
**Status:** 📋 backlog  
**Summary:** Power cycle AVR and verify EQ is active.  
**Owner:** Echo  
**Details:**
- Send `POFF` (standby) → wait 30s → `PWON` (wake) via Telnet
- Alternative: `ZM?AUDYON` apply command
- Measure a test point to confirm EQ is shaping response
- Compare pre/post measurements to verify changes

---

### Story 10 — Echo Console UI
**Status:** 📋 backlog  
**Summary:** Build a single-page UI in Echo Console for the full workflow.  
**Owner:** Echo  
**Details:**
- Tab in `index.html` (Audyssey REW Tuner SPA)
- Steps: (1) Connect AVR, (2) Run sweep per channel, (3) Generate EQ, (4) Transfer, (5) Verify
- Progress indicators per channel
- Show before/after curves on Chart.js
- Save/load calibration as `.oca` file

---

## Per-Speaker Measurement Workflow

```
FOR EACH channel IN [FL, C, FR, SBR, SBL, FHL, FHR, SW1, SW2, FDL, FDR]:
  1. Configure REW sweep level (SPL match)
  2. Start REW measurement (API call)
  3. Wait for sweep to complete (poll REW status)
  4. Fetch measurement curve (frequency/magnitude pairs)
  5. Store in session: measurements[channel] = { freq[], mag[], phase[] }
  6. Repeat for SW1 + SW2 (subwoofers use different sweep parameters)
```

**Subwoofer notes:**
- SW1/SW2 measured separately from main speakers
- Use ground plane measurement or subwoofer sweep mode in REW
- Crossover freq typically 80 Hz for subwoofers
- Double Bass setting: ON for both presets (per TCX.oca)

---

## Dispatched vs Pending

### ✅ Dispatched (completed or in active work)
| Story | Dispatched | Notes |
|-------|-----------|-------|
| Story 1 | UMIK cal file identified | Cross Spectrum Labs cal for UMIK-1 [REDACTED] exists in `calibrations/` |
| Story 2 | REW API sweep loop | `rew_to_audyssey.py` has working REW API integration |
| Story 3 | Measurement retrieval | `rew_to_audyssey.py --auto` fetches curves from REW |
| Story 7 | Binary protocol | Fully reverse-engineered in `SPEC.md`; `oca_transfer.py` working |
| Story 8 | Preset system | Preset 1/2 support added in `cb5f165`, TCX.oca = Preset 2 |
| Story 9 | Power cycle | `avr_telnet.py --power-cycle` working via Python |
| Story 10 | Echo Console UI | AVR Tools tab built in Echo Console (2026-04-25) |

### 📋 Pending (not yet started)
| Story | Notes |
|-------|-------|
| Story 4 | Target curve UI not yet built |
| Story 5 | REW match-target integration complete but not hooked to UI |
| Story 6 | Distances from REW impulse response not yet implemented |
| Story 9 | Verify step (post-transfer measurement) not automated |

---

## Legend

- 🟡 in-progress: actively being worked
- 📋 backlog: not yet started
- ✅ done: complete