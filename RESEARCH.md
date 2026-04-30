# Target Curve Research — Audyssey REW Tuner

## What is a Target Curve?

A target curve defines the **desired final frequency response** after room correction. It is NOT the correction itself — it's the goal. The room correction system (Audyssey, Dirac, etc.) computes the inverse of `(measured response - target curve)` and applies that as EQ.

A well-designed target curve:
- Compensates for room acoustics without over-correcting
- Respects speaker frequency limits and capabilities
- Aligns subwoofers with main speakers at the crossover
- Produces a natural, balanced sound matching human preference research

---

## Industry Reference: The Harman Curve

**Origin:** Dr. Sean Olive et al., Harman International (2012)
**Paper:** *A Harman Preference Target for In-Room Loudspeakers* (2012 J. Audio Eng. Soc.)

### Key Findings
- Listeners consistently preferred a **slight bass lift** (+4 to +8 dB below ~100 Hz, rolling off gradually)
- **Neutral or very slight dip in the midrange** (critical for vocal clarity)
- **Gentle downward tilt** as frequency increases above ~1-3 kHz (natural for in-room response)

### The Harman Curve Shape
```
SPL
 ^
 |  +4 to +8 dB boost below ~80-100 Hz (smooth rolloff)
 |  \
 |   \_______ flat-ish to ~1-3 kHz _________
 |                                    /
 |                                   /  gentle downward tilt
 +-------------------------------------------------> Hz
 20    100   1k    3k    10k   20k
```

### Important: Harman is a *starting point*, not a prescription
- The curve is for frequencies **above a few hundred Hz** primarily
- For bass (< 200 Hz), room modes dominate — generic curves can cause problems
- Room correction below ~200 Hz is better handled by **direct room acoustic correction**, not a fixed target curve

---

## Dirac's Approach to Target Curves

Dirac's published guidance (dirac.com/resources/target-curve) is particularly relevant as a reference for automated systems:

### Dirac-Recommended Target Curve Features
1. **Bass shelf lift:** +4 to +8 dB from ~20 Hz to ~80-100 Hz, then gradual rolloff
2. **Midrange:** Essentially flat reference (0 dB)
3. **Upper midrange/treble:** Gentle downward slope (~-3 dB at 10 kHz) — simulates in-room reflection characteristic
4. **Variable tilt** based on speaker capabilities and room size

### Key Dirac Principles
- Target curves should account for **speaker size and bass capabilities**
- Larger floorstanding speakers: target curve can be flatter (they handle bass better)
- Smaller bookshelf/satellite speakers: more bass lift needed below crossover
- Subwoofer-scaled curves: separate bass target for subwoofer channel

### What Dirac Gets Right
- **Bass management at crossover:** Subwoofer and speaker targets should align at the crossover point (+/- 0.5 dB)
- **Speaker grouping:** Left/Right mains get different treatment than surrounds/heights
- **Room-dependent bass shaping:** Below ~200 Hz, a fixed target curve is dangerous — should be derived from room modal analysis

---

## Speaker Grouping Strategy

### Group 1: Main Speakers (L/R)
- **Full range** speakers (floorstanding): flatter target, less bass boost needed
- **Limited bass** speakers (bookshelf): more bass lift below ~100 Hz
- Target curve for MLP-averaged measurement of each speaker

### Group 2: Center Channel
- **Dialog clarity priority** — must align with L/R at the crossover
- Target should match L/R above ~200 Hz for seamless imaging
- Bass contribution: typically full range, so follow L/R bass target

### Group 3: Surrounds (SLA, SRA)
- Used less frequently by content — slightly less correction aggressiveness
- Can tolerate being slightly different from mains
- Target: Harman curve starting point, with less correction below 200 Hz

### Group 4: Surround Bass (FDL, FDR, SDL, SDR)
- These are front height and surround direct bass radiators (dual-subwoofer setup in some systems)
- Follow same target as subwoofers if they play below ~80 Hz
- Otherwise treated as limited-range speakers

### Group 5: Subwoofers (SW1, SW2)
- **Room mode territory** (< 80-100 Hz): correction here is treacherous — over-correction can cause instability
- Target for subwoofers: **MLP primary position only** (position 0)
- Subwoofer target should have a **smooth bass shelf**, NOT a flat target
- Subwoofer+satellite alignment: match SPL at crossover frequency within 1-2 dB

---

## Measurement Averaging for Target Curve Generation

### Frequency Response Averaging (for speaker groups)

For each speaker group (e.g., all FL positions 0-7), compute:

**Simple average** (arithmetic mean in dB — NOT recommended alone):
```
SPL_avg(f) = (SPL_0(f) + SPL_1(f) + ... + SPL_7(f)) / 8
```
Problem: Outlier measurements with nulls will pull the average down artificially.

**Geometric mean** (logarithmic average — preferred for SPL):
```
SPL_avg(f) = 10 * log10( (10^(SPL_0(f)/10) + ... + 10^(SPL_7(f)/10) ) / 8 )
```
This is the correct acoustic averaging method — it represents the *total acoustic energy* averaged across positions.

**Weighted average** (recommended approach for MLP-centric correction):
```
weight_MLP = 2  (position 0 only — the MLP)
weight_surround = 1  (positions 1-7 — adjacent seats)

SPL_avg(f) = (2 * SPL_0(f) + sum(SPL_1(f)...SPL_7(f))) / 9
```
This gives the MLP double influence — the primary listening position gets priority while still benefiting from spatial context.

### Outlier Rejection (Robust Averaging)

Before averaging, flag measurements that deviate significantly from MLP at any frequency:

```
if |SPL_pos(f) - SPL_MLP(f)| > 10 dB at any frequency band:
    mark that position as an outlier for that frequency band
    (don't include in average for that band)
```

This prevents a single seat near a null from distorting the target.

### Subwoofer Measurement Averaging

For SW1, SW2: **MLP only (position 0)** — do NOT average across positions for subwoofers. The subwoofer's interaction with room modes is highly position-dependent. Averaging MLP + adjacent positions for subwoofer will smooth out bass peaks and nulls in a way that doesn't help the MLP.

---

## Target Curve Generation Algorithm

### Step 1: Per-Speaker Average (MLP-weighted)
For each channel ID (FL, C, FR, etc.), compute the MLP-weighted geometric average across positions 0-7.

### Step 2: Group-Level Target
For L/R/C: use direct per-speaker average.
For surrounds: use direct per-speaker average (or average of SLA+SRA as a pair).

### Step 3: Bass Shelf (Below Crossover)
Below the crossover frequency (typically 80 Hz), apply a **smooth bass shelf**:
```
target_bass(f) = base_spl + shelf_gain * (1 - log10(f / crossover_hz) / log10(20 / crossover_hz))
```
Where:
- `base_spl` = 0 dB reference
- `shelf_gain` = +4 to +8 dB (tunable)
- `crossover_hz` = chosen crossover (typically 80 Hz)

This gives a gentle boost below ~80 Hz that rolls off naturally as it approaches crossover.

### Step 4: Crossover Alignment
At the crossover frequency (e.g., 80 Hz), the subwoofer target and speaker target must match SPL within ~1 dB. Use the subwoofer MLP measurement at position 0 to anchor this.

### Step 5: High-Frequency Tilt
Above ~2-3 kHz, apply a gentle downward tilt:
```
target_hf(f) = -tilt_rate * log10(f / 3000) dB/decade
```
Where `tilt_rate` is typically **-1 to -2 dB/decade** for in-room response (more reflective than anechoic).

### Step 6: Smoothing
Apply 1/3-octave smoothing to the target curve to prevent over-EQing at narrow peaks. Many room correction systems do this automatically (Audyssey, Dirac), but if generating a custom target, smooth it before exporting.

---

## Suggested Tunable Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| `bass_shelf_gain` | +2 to +10 dB | +6 dB | Bass lift below ~100 Hz |
| `bass_shelf_start` | 40-120 Hz | 80 Hz | Where bass shelf begins |
| `hf_tilt_rate` | 0 to -3 dB/decade | -1.5 dB/decade | High-frequency downward tilt |
| `tilt_start_hz` | 1-5 kHz | 3 kHz | Where HF tilt begins |
| `crossover_freq` | 60/80/100/120 Hz | 80 Hz | Subwoofer/speaker crossover |
| `mlp_weight` | 1-3 | 2 | MLP weight in position averaging |
| `outlier_threshold_db` | 5-15 dB | 10 dB | dB deviation threshold for outlier rejection |
| `smoothing_octave` | 1/6 to 1/2 oct | 1/3 oct | Smoothing bandwidth |

---

## Implementation Checklist

- [ ] Parse ADY measurements into per-channel, per-position arrays
- [ ] Implement MLP-weighted geometric mean per channel
- [ ] Implement outlier rejection (flag positions deviating > threshold from MLP)
- [ ] Subwoofer channel: use MLP-only (position 0), no averaging
- [ ] Generate bass shelf using tunable `bass_shelf_gain` and `bass_shelf_start`
- [ ] Compute crossover-aligned subwoofer target
- [ ] Apply HF tilt above `tilt_start_hz`
- [ ] Apply 1/3-octave smoothing
- [ ] Output as `.frd` file or push directly to REW
- [ ] GUI: allow tuning all parameters with live preview

---

## Key Research Sources

1. **Olive & Olive** — *A Harman Preference Target for In-Room Loudspeakers*, J. Audio Eng. Soc. (2012)
2. **Dirac Academy** — *What is the best target curve for room correction?* (dirac.com/resources/target-curve)
3. **AVS Forum** — Audyssey measurement averaging and MLP-weighted correction threads
4. **REW Help** — *Making Measurements* and averaging multiple positions (roomeqwizard.com/help)
5. **SVS Sound** — *Tips for Setting the Proper Crossover Frequency* (svsound.com)
6. **Audio Science Review** — Harman curve discussion, house curve threads

---

## Open Questions for Further Research

1. **Subwoofer placement vs MLP alignment:** If SW1 and SW2 are placed symmetrically, should their MLP measurements be averaged together before target generation?
2. **Target curve per speaker vs group target:** Should all main speakers (L/C/R) share one averaged target, or each get their own tailored target?
3. **Time-of-flight correction:** Should target curves account for arrival time differences between speaker positions? (Group delay alignment at crossover)
4. **Multi-subwoofer correlation:** If SW1 and SW2 are uncorrelated (different content), their measurements shouldn't be averaged — but if they play the same bass content, should they be averaged?

---

*Last updated: 2026-04-30 — Initial research compilation*
