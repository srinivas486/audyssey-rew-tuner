# Smart Target Curve — Epic + Stories Breakdown
# Project: audyssey-rew-tuner
# Status: DRAFT — pending Vasu approval via main

## Design Answers

### Q1: LF Cutoff Detection
Use the speaker's own measured response. Reference window: 200–500 Hz smoothed SPL. Cutoff = lowest frequency where SPL has dropped ≥ 10 dB below reference. Below cutoff: modelled HPF rolloff.

### Q2: Subwoofer Targets — Shared or Separate?
**Separate SW1 and SW2 curves.** Each subwoofer has its own room mode behaviour at the MLP. Averaging would smooth out nulls that affect the MLP at that seat.

### Q3: Should target ever reduce SPL (cut peaks)?
**No — target is a floor, not a surgeon.** The HPF shaping prevents the target from demanding impossible bass extension. The EQ cuts what it needs to; the target sets the minimum demand.

### Q4: Per-speaker or one-target-fits-all?
**Per-speaker for main channels.** FL, C, FR each get their own HPF-shaped target. All converge at 80 Hz crossover within ±1 dB. Surrounds share a lighter target.

---

## EPIC: Smart Channel-Specific Target Curves

**Goal:** Replace generic Harman curve with per-channel curves that respect physical low-frequency limits, subwoofer extension floor, and 80 Hz crossover alignment.

---

## STORY 1 — Subwoofer LPF Shaping + Crossover Alignment
**Priority: 1**

### Task 1.1 — Subwoofer LF Floor Detection
**File:** `target_curve.py`
- Add `detect_lf_floor(freq_hz, spl_db, ref_db=None) → (floor_hz, ref_db)`
- Reference: smoothed average SPL in 20–80 Hz window
- Floor = lowest frequency where SPL ≥ 10 dB below reference
- Returns ref_db for crossover anchoring
- TDD: synthetic flat response, rolloff response, deep null

### Task 1.2 — Subwoofer Target Curve Generation
**File:** `target_curve.py`
- Add `generate_subwoofer_target(freq_hz, spl_db, params, ref_db) → (freq, target_db)`
- Below LF floor: smooth HPF-style taper
- LF floor → 80 Hz: flat shelf at `shelf_gain` dB above ref level
- At 80 Hz: anchor to `ref_db + shelf_gain`
- 1/3-octave smoothing on output
- TDD: crossover anchor within 1 dB of target

### Task 1.3 — SW1/SW2 Per-Subwoofer Targets
**File:** `target_curve.py`
- Add `generate_all_subwoofer_targets(channel_freq_responses, params)`
- Filter to SUBWOOFER_IDS
- MLP-only (position 0) — NOT averaged across positions
- Returns dict: commandId → (freq, target_db)

### Task 1.4 — Crossover Alignment Verification
**File:** `tests/test_target_curve.py`
- Add `test_crossover_alignment()`: verify SW and speaker targets match within 1 dB at crossover_freq

### Task 1.5 — FRD Export + REW API Push for Subwoofer Targets
**File:** `rew_exporter.py`
- Add `export_subwoofer_targets()`, `push_subwoofer_targets_via_api()`
- Uses same REW `/import/frequency-response-data` endpoint

---

## STORY 2 — Speaker HPF Shaping
**Priority: 2**

### Task 2.1 — Speaker LF Cutoff Detection
**File:** `target_curve.py`
- Add `detect_lf_cutoff(freq_hz, spl_db) → (cutoff_hz, ref_db)`
- Reference window: 200–500 Hz average SPL (smoothed 1/3-octave)
- Cutoff = lowest frequency where SPL ≥ 10 dB below reference
- TDD: flat response, bookshelf ~80 Hz cutoff, floorstanding ~30 Hz cutoff

### Task 2.2 — HPF-Shaped Target for Main Speakers
**File:** `target_curve.py`
- Add `generate_speaker_target(freq_hz, spl_db, params, cutoff_hz, ref_db) → (freq, target_db)`
- Below cutoff: modelled 2nd-order HPF rolloff (smooth)
- Above cutoff to HF tilt start: flat at ref level
- HF tilt: same Harman tilt above `params.tilt_start_hz`
- 1/3-octave smoothing
- TDD: target never demands >10 dB boost below cutoff

### Task 2.3 — Per-Speaker Targets (FL, C, FR)
**File:** `target_curve.py`
- Add `generate_all_speaker_targets(channel_freq_responses, params)`
- Filter to MAIN_CHANNEL_IDS
- Returns dict: commandId → (freq, target_db)

### Task 2.4 — FRD Export + REW API Push for Speaker Targets
**File:** `rew_exporter.py`
- Add `export_speaker_targets()`, `push_speaker_targets_via_api()`

---

## STORY 3 — Surround Channel Handling
**Priority: 3**

### Task 3.1 — Surround Speaker Classification
**File:** `target_curve.py`
- Add `SURROUND_CHANNEL_IDS`, `is_surround(commandId) → bool`

### Task 3.2 — Lighter Surround Target
**File:** `target_curve.py`
- Add `generate_surround_target(freq_hz, spl_db, params) → (freq, target_db)`
- Same HPF detection as main speakers
- Gentler bass shelf: `shelf_gain * 0.6`
- Same HF tilt as main speakers

### Task 3.3 — Surround Target Export
**File:** `rew_exporter.py`
- Add `export_surround_targets()`, `push_surround_targets_via_api()`

---

## STORY 4 — Tunable Parameters via CLI + Config File
**Priority: 4**

### Task 4.1 — CLI Arguments
**File:** `main.py`
- `--target-curve` (flag)
- `--bass-shelf-gain` (default 5.0 dB)
- `--bass-shelf-start` (default 80 Hz)
- `--hf-tilt-start` (default 2000 Hz)
- `--hf-tilt-rate` (default 1.5 dB/decade)
- `--crossover-freq` (default 80 Hz)
- `--hpf-cutoff-threshold` (default 10 dB)
- `--channel` filter
- `--export-format` (frd | api | both)

### Task 4.2 — JSON Config File
**File:** `target_curve_params.json` + `target_curve_params.example.json`
- Schema matching `TargetCurveParams` dataclass
- `main.py --config FILE` loads from file
- CLI flags override config file values

### Task 4.3 — Summary Output
**File:** `main.py`
- Per-channel: curve type, LF cutoff/floor, bass shelf gain, crossover anchor SPL
- Output files + API push results

---

## File Changes

| File | Changes |
|---|---|
| `target_curve.py` | New: detect_lf_floor(), detect_lf_cutoff(), generate_subwoofer_target(), generate_speaker_target(), generate_surround_target(), generate_all_subwoofer_targets(), generate_all_speaker_targets(); Updated: TargetCurveParams with HPF params |
| `rew_exporter.py` | New: subwoofer/speaker/surround-specific export + API push |
| `main.py` | CLI with tunable params + config file support |
| `tests/test_target_curve.py` | Tests for all new functions + crossover alignment validation |
| `target_curve_params.example.json` | Example config |

---

## Open Questions for Vasu

1. **Crossover anchor level:** At 80 Hz, should SW target be anchored to the *measured* MLP SPL at 80 Hz (natural), or to `ref_db + shelf_gain` (slightly louder)? Natural = no perceived bass change at crossover; `+shelf_gain` = +5 dB louder. Which does Vasu prefer?
2. **HPF cutoff threshold:** 10 dB is aggressive — should it be tunable? Default 10 dB, range 6–15 dB.
3. **Phase alignment at crossover:** SPL alignment is fine for MVP, but should we also request group delay correction at 80 Hz in REW?

---

_Orion — awaiting Vasu's approval via main before dispatching to developer_
