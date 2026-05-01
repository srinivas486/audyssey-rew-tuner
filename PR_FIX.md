## Problem

The old `generate_house_curve` computed a house curve by averaging measured speaker/subwoofer responses and anchoring everything to absolute SPL from the measurement. This produced a curve that was 100% driven by measurement quality — not a target response:

- Subwoofer shelf at **+12 to +15 dB** (measurement artifact)
- Speakers below crossover at **-13 to 0 dB** (measurement-dependent)

Visually it maxed out around 93 Hz because that's where the subwoofer data blended with the wildly off-level speaker data.

## Fix

Replaced with the same algorithm as the old `generate_target_curve_from_ady` — a **Harman research curve** (a preferred response shape, independent of measurement):

```
10 Hz:  +5.00 dB  (bass shelf peak)
80 Hz:   0.00 dB  (shelf crosses neutral)
200-500 Hz: 0.00 dB  (flat midrange)
2 kHz:  0.00 dB  (tilt starts)
20 kHz: -1.38 dB  (gentle HF tilt)
```

### Algorithm
1. Start at **0 dB neutral** (flat reference)
2. **Bass shelf**: +5 dB at 20 Hz, rolls off to 0 dB at 80 Hz (Harman research)
3. **HF tilt**: -1.5 dB/decade above 2 kHz
4. **Optional absolute SPL**: when `--target-spl 85` is set, shift the entire curve so midrange sits at 85 dB
5. **1/3-octave smoothing**

### With `--target-spl 85`
```
10 Hz:  +88.38 dB
80 Hz:  +83.87 dB
20 kHz: +82.00 dB  (full curve shifted +85 dB from neutral)
```

## Testing
python3 -m pytest tests/ --tb=short -q  # 103 passed

Closes #35 (supersedes).
