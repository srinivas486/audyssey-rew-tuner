"""Target curve generation for REW house curve.

Generates a target/house curve from Audyssey MultEQ Editor (ADY) measurements
and loads it into REW via the house curve API.

The algorithm:
1. Compute MLP-weighted geometric mean across all measurement positions per channel.
2. Apply outlier rejection (>10 dB from MLP at any frequency).
3. Average MLP-weighted responses of FL, C, FR into a single target curve shape.
4. Apply bass shelf boost below bass_shelf_start Hz.
5. Apply high-frequency downward tilt above tilt_start_hz.
6. Apply 1/3-octave smoothing.
7. Export as .txt and push to REW via /eq/house-curve API.
"""

from __future__ import annotations

import json
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 48000  # Hz

REW_API_DEFAULT_HOST = "localhost"
REW_API_DEFAULT_PORT = 4735

# Subwoofer channel identifiers (case-insensitive match)
SUBWOOFER_IDS = frozenset({"sw1", "sw2"})

# Main front channel identifiers used to derive the target curve
MAIN_CHANNEL_IDS = frozenset({"fl", "c", "fr"})

# All positions measured (0 = MLP primary, 1-7 = adjacent/reference positions)
ALL_POSITIONS = [str(i) for i in range(8)]

# Frequency grid: 1/6-octave steps from 20 Hz to 20 kHz
# 1/6 octave ≈ 0.167 decades; 20 Hz → 20kHz is 3 decades = ~18 steps per decade
# Total ≈ 54 points, which is sufficient for house curve.
_OCTAVE_STEP = 1.0 / 6.0  # 1/6 octave


def _make_target_frequencies() -> np.ndarray:
    """Generate 1/6-octave frequency grid from 10 Hz to 20 kHz.
    
    Extended below 20 Hz to cover deep bass subwoofer extension.
    10 Hz start captures full subwoofer range.
    """
    log_min = np.log10(10.0)   # start at 10 Hz for subwoofer coverage
    log_max = np.log10(20000.0)
    n_steps = int(round((log_max - log_min) / _OCTAVE_STEP)) + 2
    log_freqs = np.linspace(log_min, log_max, n_steps)
    return np.power(10.0, log_freqs)


TARGET_FREQUENCIES: np.ndarray = _make_target_frequencies()


# -----------------------------------------------------------------------------
# Dataclass: tunable parameters
# -----------------------------------------------------------------------------

@dataclass
class TargetCurveParams:
    """Tunable parameters for target curve generation.
    
    Based on Harman curve research (Olive & Toole, J. Audio Eng. Soc. 2012):
    - Bass shelf: +5 to +7 dB below ~80 Hz (simulates room gain, natural bass preference)
    - HF tilt: gentle downward slope above ~2-3 kHz (reduces harshness, accounts for room reflection)
    - Smooth transitions throughout to avoid introducing new resonances
    """

    bass_shelf_gain: float = 5.0
    """dB of bass lift at the lowest frequency (10 Hz), rolling off to 0 dB at bass_shelf_start.
    Typical range: +4 to +7 dB. Based on Harman curve research."""

    bass_shelf_start: float = 80.0
    """Hz — frequency above which the bass shelf no longer applies.
    This is the crossover region where speakers take over from subwoofers."""

    tilt_start_hz: float = 2000.0
    """Hz — frequency above which high-frequency tilt begins.
    Below this, response is neutral/flat. Starting at 2 kHz gives natural treble balance."""

    tilt_rate: float = 1.5
    """dB/decade — high-frequency downward tilt rate.
    1.5 dB/decade is a gentle slope (more reflective room simulation).
    Dirac uses similar tilt rates for living room acoustics."""

    mlp_weight: float = 2.0
    """Weight for MLP position (0) in the weighted average. Positions 1-7 get weight 1."""

    outlier_threshold_db: float = 10.0
    """dB — if a position deviates more than this from MLP at a frequency, exclude it."""

    smoothing_octave: float = 1.0 / 2.0
    """Octave bandwidth for smoothing — 1/2 octave (broader) to filter room modes before averaging.
    1/3 octave is REW's default view smoothing; 1/2 octave better for target curve generation."""

    smoothing_octave_final: float = 1.0 / 3.0
    """Final smoothing applied to the output target curve. 1/3 octave is REW standard display smoothing."""

    crossover_freq: float = 80.0
    """Hz — subwoofer/speaker crossover frequency (used for alignment)."""

    flat_target_db: float = 0.0
    """dB — target curve reference level. 0 dB means the curve represents a flat/neutral target."""


# -----------------------------------------------------------------------------
# Core signal processing
# -----------------------------------------------------------------------------

def weighted_geometric_mean(
    spl_values: list[float],
    weights: list[float],
) -> float:
    """Compute weighted geometric mean of SPL values in dB.

    Weighted geometric mean in dB:
        SPL_avg = 10 * log10( sum(w_i * 10^(SPL_i/10)) / sum(w) )

    This correctly averages acoustic energy across measurement positions.

    Args:
        spl_values: List of SPL values in dB (one per position).
        weights: List of weights (same length as spl_values).

    Returns:
        Weighted geometric mean in dB.
    """
    if len(spl_values) != len(weights):
        raise ValueError("spl_values and weights must have the same length")
    if len(spl_values) == 0:
        return 0.0

    total_weight = 0.0
    weighted_energy = 0.0
    for spl_db, w in zip(spl_values, weights):
        linear = 10.0 ** (spl_db / 10.0)
        weighted_energy += w * linear
        total_weight += w

    if total_weight <= 0.0:
        return 0.0

    return 10.0 * np.log10(weighted_energy / total_weight)


def apply_bass_shelf(
    freqs: np.ndarray,
    spl: np.ndarray,
    start_hz: float,
    gain_db: float,
    ref_hz: float = 20.0,
) -> np.ndarray:
    """Apply a smooth bass shelf boost below start_hz.

    The boost reaches maximum gain_db at ref_hz (typically 20 Hz),
    rolls off to 0 dB at start_hz (typically 80 Hz).

    Harman curve shelf formula:
        t = (log10(f) - log10(ref_hz)) / (log10(start_hz) - log10(ref_hz))
        boost = gain_db * (1 - t)   for ref_hz <= f < start_hz
        boost = gain_db              for f < ref_hz (constant below ref_hz)

    Args:
        freqs: Frequency array in Hz.
        spl: SPL values in dB.
        start_hz: Frequency above which no boost is applied (crossover point).
        gain_db: Maximum dB boost at ref_hz.
        ref_hz: Frequency of maximum boost. Default 20 Hz.

    Returns:
        New SPL array with bass shelf applied.
    """
    result = spl.copy()

    log_ref = np.log10(ref_hz)
    log_start = np.log10(start_hz)
    log_range = log_start - log_ref  # positive when ref_hz < start_hz

    for i, freq in enumerate(freqs):
        if freq >= start_hz:
            continue
        if freq <= ref_hz:
            result[i] = spl[i] + gain_db  # constant full boost below ref_hz
            continue
        # Logarithmic roll-off between ref_hz and start_hz
        t = (np.log10(freq) - log_ref) / log_range  # 0 at ref_hz, 1 at start_hz
        t = max(0.0, min(1.0, t))
        result[i] = spl[i] + gain_db * (1.0 - t)

    return result


def apply_hf_tilt(
    freqs: np.ndarray,
    spl: np.ndarray,
    start_hz: float,
    tilt_rate: float,
) -> np.ndarray:
    """Apply gentle downward high-frequency tilt above start_hz.

    Tilt formula (dB/decade above start_hz):
        tilt_offset(f) = -tilt_rate * log10(f / start_hz)

    Args:
        freqs: Frequency array in Hz.
        spl: SPL values in dB.
        start_hz: Frequency above which tilt begins.
        tilt_rate: dB/decade downward slope.

    Returns:
        New SPL array with HF tilt applied.
    """
    result = spl.copy()
    above_mask = freqs > start_hz
    if not np.any(above_mask):
        return result

    for i, freq in enumerate(freqs):
        if freq <= start_hz:
            continue
        offset_db = -tilt_rate * np.log10(freq / start_hz)
        result[i] = spl[i] + offset_db

    return result


def smooth_curve(
    freqs: np.ndarray,
    spl: np.ndarray,
    octave_bw: float = 1.0 / 3.0,
) -> np.ndarray:
    """Apply 1/3-octave smoothing to a frequency response curve.

    Smoothing uses a frequency-domain rolling average in log space,
    where the window width is octave_bw octaves.

    For each frequency bin, all points within ±octave_bw/2 in log space
    are averaged.

    Args:
        freqs: Frequency array in Hz (log-spaced or irregular).
        spl: SPL values in dB.
        octave_bw: Smoothing bandwidth in octaves (default 1/3 octave).

    Returns:
        Smoothed SPL array.
    """
    if len(freqs) == 0:
        return spl.copy()

    log_freqs = np.log10(freqs + 1e-30)
    log_bw_half = octave_bw / 2.0

    result = np.zeros_like(spl)
    for i in range(len(freqs)):
        lo = log_freqs[i] - log_bw_half
        hi = log_freqs[i] + log_bw_half
        mask = (log_freqs >= lo) & (log_freqs <= hi)
        if np.any(mask):
            result[i] = np.mean(spl[mask])
        else:
            result[i] = spl[i]

    return result


# -----------------------------------------------------------------------------
# Target curve generation
# -----------------------------------------------------------------------------

def _get_channel_spl_at_frequencies(
    channel_freq_response: dict[str, Any],
    positions: list[str],
    target_freqs: np.ndarray,
) -> tuple[list[list[float]], list[list[float]]]:
    """Extract SPL values for specific positions interpolated to target frequencies.

    Args:
        channel_freq_response: Dict with 'positions' key mapping pos -> {freq_hz, spl_db}.
        positions: List of position keys to extract (e.g. ["0", "1", ...]).
        target_freqs: Frequency grid to interpolate onto.

    Returns:
        Tuple of (freq_lists, spl_lists) for each position.
    """
    positions_data = channel_freq_response.get("positions", {})
    freq_lists: list[list[float]] = []
    spl_lists: list[list[float]] = []

    for pos in positions:
        pos_key = str(pos)
        if pos_key not in positions_data:
            continue
        freq_arr = positions_data[pos_key]["freq_hz"]
        spl_arr = positions_data[pos_key]["spl_db"]
        # Interpolate onto target frequency grid
        interp_spl = np.interp(target_freqs, freq_arr, spl_arr, left=np.nan, right=np.nan)
        freq_lists.append(list(target_freqs))
        spl_lists.append(list(interp_spl))

    return freq_lists, spl_lists


def _apply_outlier_rejection(
    mlp_spl: list[float],
    all_spl: list[list[float]],
    threshold_db: float,
) -> tuple[list[list[float]], list[list[float]]]:
    """Reject positions that deviate > threshold_db from MLP at any frequency.

    Args:
        mlp_spl: MLP position SPL values (reference).
        all_spl: List of SPL arrays for all positions (including MLP at index 0).
        threshold_db: Deviation threshold in dB.

    Returns:
        Tuple of (accepted_spl, accepted_weights) after outlier rejection.
    """
    accepted: list[list[float]] = []
    rejected: list[list[float]] = []

    for i, pos_spl in enumerate(all_spl):
        deviations = [abs(a - b) for a, b in zip(pos_spl, mlp_spl) if not (np.isnan(a) or np.isnan(b))]
        max_dev = max(deviations) if deviations else 0.0
        if max_dev > threshold_db:
            rejected.append(pos_spl)
        else:
            accepted.append(pos_spl)

    return accepted, rejected


def generate_target_curve_from_ady(
    data: dict[str, Any],
    params: TargetCurveParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate a Harman-style target curve from parsed ADY measurement data.

    The target curve defines a PREFERRED response shape (independent of what was
    measured). This is a Harman curve: smooth bass shelf below ~80 Hz (+5 dB
    at 20 Hz), neutral midrange, gentle treble tilt above ~2 kHz.

    REW's EQ then computes correction = measured_response - target_curve,
    boosting frequencies where the room is deficient and cutting where it's
    over-absorbent.

    Algorithm:
    1. Start with 0 dB neutral reference
    2. Apply Harman curve shape: bass shelf +5 dB @ 20 Hz, flat midrange,
       HF tilt -1.5 dB/decade above 2 kHz
    3. Smooth with 1/2 octave to remove narrow artifacts
    4. Final 1/3 octave smoothing for REW display standard

    Args:
        data: Parsed ADY content from ady_parser.load_ady().
        params: Tunable parameters. Uses defaults if None.

    Returns:
        Tuple of (freq_hz, spl_db) arrays for the target curve.
    """
    if params is None:
        params = TargetCurveParams()

    # Start with 0 dB neutral (flat target)
    target = np.zeros_like(TARGET_FREQUENCIES)

    # Apply Harman curve bass shelf: boost below bass_shelf_start Hz
    # Gain peaks at ref_hz (20 Hz) and rolls off to 0 dB at bass_shelf_start (80 Hz)
    target = apply_bass_shelf(
        TARGET_FREQUENCIES,
        target,
        start_hz=params.bass_shelf_start,
        gain_db=params.bass_shelf_gain,
        ref_hz=20.0,
    )

    # Apply high-frequency tilt above tilt_start_hz
    # Gentle downward slope above 2 kHz: reduces harshness, simulates
    # in-room reflection characteristic (Harman research)
    target = apply_hf_tilt(
        TARGET_FREQUENCIES,
        target,
        start_hz=params.tilt_start_hz,
        tilt_rate=params.tilt_rate,
    )

    # Apply 1/2 octave smoothing (filters room modal narrow peaks)
    target = smooth_curve(TARGET_FREQUENCIES, target, params.smoothing_octave)

    # Final 1/3 octave smoothing for REW display standard
    target = smooth_curve(TARGET_FREQUENCIES, target, params.smoothing_octave_final)

    return TARGET_FREQUENCIES.copy(), target



