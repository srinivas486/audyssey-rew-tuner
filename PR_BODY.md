## Summary

Story 1 implements subwoofer target curve generation with LPF shaping and crossover alignment for the Audyssey REW Tuner.

## Changes

### New functions in target_curve.py
- detect_lf_floor() — detects the subwoofer low-frequency floor from measured response (ref = mean SPL 20-80 Hz; floor = first in-band freq where SPL crosses above ref - threshold)
- generate_subwoofer_target() — generates a subwoofer target curve with a smooth rolloff below the LF floor, a shelf gain above ref_db, and MLP-anchored crossover alignment at 80 Hz
- generate_all_subwoofer_targets() — generates targets for SW1 and SW2 separately using MLP position 0 data
- export_subwoofer_target() — exports subwoofer target to .frd file
- push_subwoofer_target_via_api() — pushes subwoofer target to REW via the HTTP API

### New parameters in TargetCurveParams
- lf_floor_threshold_db: float = 10.0 — dB below ref to search for LF floor
- shelf_gain: float = 5.0 — dB above ref for subwoofer shelf level

### Test coverage
- tests/test_subwoofer_target.py — 22 tests covering all 5 tasks

### Documentation
- SMART_TARGET_CURVE_DESIGN.md — design specification

## Acceptance Criteria
- [x] TDD: all 22 tests pass
- [x] detect_lf_floor correctly identifies the LF floor using cross-up semantics
- [x] generate_subwoofer_target produces smooth shelf below crossover anchored to MLP at 80 Hz
- [x] SW1 and SW2 get separate targets (not combined or averaged)
- [x] export_subwoofer_target writes valid .frd format
- [x] push_subwoofer_target_via_api correctly calls REW API with base64 float32 encoding
- [x] Pure numpy — no scipy dependency
- [x] All 82 tests in the full test suite pass

## Testing
python3 -m pytest tests/test_subwoofer_target.py -v
python3 -m pytest tests/ --tb=short -q
