# Smart Target Curve Design

## Epic: Smart Channel-Specific Target Curves

**Project:** audyssey-rew-tuner
**Status:** Designed — pending implementation
**GitHub Epic:** [#25](https://github.com/srinivas486/audyssey-rew-tuner/issues/25)

---

## Overview

Replace the current generic Harman-style target curve with per-channel curves that:
1. Respect each speaker's physical low-frequency limits (HPF rolloff)
2. Respect subwoofer extension floor (LPF shaping)
3. Align at 80 Hz crossover within 1 dB
4. Never demand correction a speaker can't physically produce
5. Apply lighter correction for surround channels

---

## Current State

`target_curve.py` currently generates a **single generic Harman curve** applied uniformly to all channels:
- +5 dB bass shelf at 20 Hz, rolling off to 0 dB at 80 Hz
- Flat midrange (0 dB relative)
- -1.5 dB/decade HF tilt above 2 kHz
- Same for all speakers and subwoofers

This ignores each speaker's physical limits and the subwoofers' actual extension.

---

## Stories

| # | Story | Priority | GitHub Issue |
|---|---|---|---|
| 1 | Subwoofer LPF Shaping + Crossover Alignment | P0 | [#26](https://github.com/srinivas486/audyssey-rew-tuner/issues/26) |
| 2 | Speaker HPF Detection and Target Shaping | P1 | [#30](https://github.com/srinivas486/audyssey-rew-tuner/issues/30) |
| 3 | Surround Channel Handling | P2 | [#31](https://github.com/srinivas486/audyssey-rew-tuner/issues/31) |
| 4 | Tunable Parameters via CLI + Config File | P3 | [#32](https://github.com/srinivas486/audyssey-rew-tuner/issues/32) |
| 5 | Per-Channel Target Curve File Export + REW API Push | P0 | [#33](https://github.com/srinivas486/audyssey-rew-tuner/issues/33) |

---

## Technical Approach

### Channel Groups

| Group | Channels | Approach |
|---|---|---|
| **Main Speakers** | FL, C, FR | HPF-shaped target per speaker; 80 Hz anchor |
| **Subwoofers** | SW1, SW2 | MLP-only (position 0); LPF floor detection; +5 dB shelf to 80 Hz |
| **Surrounds** | SLA, SRA | Lighter HPF target (bass shelf × 0.6) |
| **Surround Bass** | FDL, FDR, SDL, SDR | Subwoofer LPF if below 80 Hz; else surround HPF |

### LF Cutoff Detection — Speakers

**Algorithm (`detect_lf_cutoff()`):**
1. Smooth measured SPL with 1/3-octave
2. Reference level = average SPL in 200–500 Hz window
3. Cutoff = lowest frequency where SPL has dropped ≥ N dB below reference (N = `hpf_cutoff_threshold_db`, default 10 dB)
4. Returns `(cutoff_hz, ref_db)`

**HPF-Shaped Target below cutoff:**
- `cutoff_hz` to `(cutoff_hz × 1.5)`: smooth ramp from ref_db to natural rolloff
- Below `(cutoff_hz × 0.5)`: modelled HPF rolloff shape — no demand above physical limit
- **Guard:** target never demands >10 dB boost below cutoff

### LF Floor Detection — Subwoofers

**Algorithm (`detect_lf_floor()`):**
1. Use MLP-only (position 0) — room modes are position-specific; don't average
2. Reference level = average SPL in 20–80 Hz window
3. Floor = lowest frequency where SPL drops ≥ 10 dB below reference
4. Returns `(floor_hz, ref_db)`

**LPF-Shaped Target:**
- Below floor: smooth HPF-style taper toward 0 dB (sub can't produce below this)
- Floor to 40 Hz: rise to full +shelf_gain dB shelf
- 40 Hz to 80 Hz: flat shelf
- **80 Hz anchor:** subwoofer target = speaker target ± 1 dB

### Crossover Alignment at 80 Hz

1. After computing main speaker targets, average their SPL at 80 Hz → `speaker_80hz_spl`
2. Adjust subwoofer target so at 80 Hz: `subwoofer_80hz_spl = speaker_80hz_spl`
3. This ensures seamless bass integration — no dip or peak at the crossover

### HF Tilt (all channels)

- Above `params.tilt_start_hz` (default 2000 Hz): `-params.tilt_rate dB/decade` (Harman standard)
- 1/3-octave smoothing on final output

---

## New Functions to Add to `target_curve.py`

| Function | Purpose |
|---|---|
| `detect_lf_floor(freq, spl)` | Find subwoofer extension floor |
| `detect_lf_cutoff(freq, spl)` | Find speaker LF cutoff |
| `generate_subwoofer_target(freq, spl, params, ref_db)` | SW1/SW2 LPF target |
| `generate_speaker_target(freq, spl, params, cutoff_hz, ref_db)` | FL/C/FR HPF target |
| `generate_surround_target(freq, spl, params)` | SLA/SRA lighter target |
| `generate_all_subwoofer_targets(data, params)` | Aggregate for SW1, SW2 |
| `generate_all_speaker_targets(data, params)` | Aggregate for FL, C, FR |
| `generate_all_surround_targets(data, params)` | Aggregate for surrounds |

### Updated `TargetCurveParams` Fields

| Field | Default | Description |
|---|---|---|
| `hpf_cutoff_threshold_db` | 10.0 | dB below ref to detect LF cutoff |
| `surround_bass_scale` | 0.6 | Multiplier for surround bass shelf |
| *(existing)* | | |

---

## Files to Modify

| File | Changes |
|---|---|
| `target_curve.py` | New functions above; updated `TargetCurveParams` |
| `rew_exporter.py` | Per-channel FRD export + API push |
| `tests/test_target_curve.py` | TDD tests for all new functions |
| `target_curve_params.example.json` | Annotated example config |

---

## Key Technical Decisions

1. **Per-subwoofer targets (not averaged):** SW1 and SW2 each get their own curve. Averaging would smooth out nulls that matter at the MLP.

2. **MLP-only for subwoofers:** Room modes are highly position-dependent. Averaging MLP + adjacent seats for subwoofers would give an incorrect target for the MLP.

3. **10 dB cutoff threshold:** Aggressive but reasonable default. The target demands correction above this point, but gracefully tapers below — preventing over-correction. Tunable from 6–15 dB.

4. **Separate SW anchor at 80 Hz:** Subwoofer target is anchored to the speaker target at crossover, not to its own natural response. This ensures seamless bass integration.

5. **Surround bass shelf at 60% of main:** Reflects that surrounds are used less frequently and don't need full correction aggressiveness.

---

## Open Questions for Vasu

1. **Crossover anchor level:** At 80 Hz, should the SW target be anchored to the *measured* MLP SPL at 80 Hz (natural level), or to `ref_db + shelf_gain` (+5 dB louder)? Natural = no perceived bass change at crossover; `+shelf_gain` = noticeable bass lift at the crossover point.

2. **HPF cutoff threshold:** 10 dB is the default. Should it be configurable? Range 6–15 dB. Too low (6 dB) = more correction demanded; too high (15 dB) = less correction demanded.

3. **Phase alignment at crossover:** MVP targets only SPL alignment (amplitude). Should we also address group delay / phase alignment at 80 Hz in a future story?

---

## References

- RESEARCH.md — Harman curve research, Dirac approach, averaging strategy
- target_curve.py — current implementation (generic Harman curve)
- [Harman Curve Paper](https://www.eesforensicengineering.com/wp-content/uploads/2018/02/OLIVE_Second_Order_Preference_Curve_JAES56_7_8_July_August_2008.pdf) — Olive & Toole, J. Audio Eng. Soc. (2012)
- REW house curve API: `POST /eq/house-curve`
