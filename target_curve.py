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

import rew_exporter


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

    target_spl_db: float | None = None
    """dB SPL — absolute target SPL at midrange. None = auto from measurement ref."""

    subwoofer_ref_offset_db: float = 0.0
    """dB — shifts subwoofer target relative to measured ref.
    Positive = lower subwoofer, negative = higher subwoofer."""

    blend_octaves: float = 0.5
    """Octaves — crossover blend width each side of crossover_freq."""

    lf_floor_threshold_db: float = 10.0
    """dB below ref — threshold for detecting the low-frequency floor in subwoofer response."""

    shelf_gain: float = 5.0
    """dB above ref — target shelf level for subwoofer LF extension (default +5 dB)."""

    hpf_cutoff_threshold_db: float = 12.0
    """dB below midrange ref for HPF cutoff detection in speaker response."""


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


# -----------------------------------------------------------------------------
# Story 1 — Subwoofer LPF Shaping + Crossover Alignment
# -----------------------------------------------------------------------------

def detect_lf_floor(
    freq_hz: np.ndarray,
    spl_db: np.ndarray,
    threshold_db: float = 10.0,
) -> tuple[float, float]:
    """Detect the low-frequency floor from a measured subwoofer response.

    Reference level = mean SPL in 20–80 Hz window.
    Floor = lowest frequency where SPL first drops BELOW ref_db - threshold_db.

    Args:
        freq_hz: Measured frequency bins (Hz). Need not be sorted but
            the function treats indices as aligned with spl_db.
        spl_db: Measured SPL values in dB (same length as freq_hz).
        threshold_db: dB below the reference window average to search
            for the floor. Default 10 dB.

    Returns:
        Tuple of (floor_hz, ref_db) where floor_hz is the detected low-
        frequency floor in Hz (or the lowest frequency in the array if
        no floor is found), and ref_db is the reference mid-bass level
        (mean SPL in the 20–80 Hz window).
    """
    # Compute reference level from 20–80 Hz window
    in_range = (freq_hz >= 20.0) & (freq_hz <= 80.0)
    ref_values = spl_db[in_range]
    if len(ref_values) == 0:
        ref_db = float(np.mean(spl_db))
    else:
        ref_db = float(np.mean(ref_values))

    threshold = ref_db - threshold_db

    # Find the low-frequency floor using "cross-up" logic:
    # The subwoofer response typically rises from a low rolloff toward the
    # reference level as frequency increases. The floor is the frequency
    # where the response first ENTERS the "above-threshold" region from below.
    # This corresponds to the first freq in the 20–80 Hz band whose SPL >= threshold
    # AND whose previous measured point (if any) had SPL < threshold.
    #
    # Special cases:
    #   - If the lowest freq in the 20–80 Hz band is already >= threshold,
    #     the floor is the lowest freq (subwoofer extends cleanly).
    #   - If no freq in the 20–80 Hz band is >= threshold, floor is the
    #     lowest frequency (response is entirely below threshold).
    band_mask = (freq_hz >= 20.0) & (freq_hz <= 80.0)
    if not np.any(band_mask):
        # No data in the band — fallback to lowest frequency
        floor_hz = float(freq_hz[0])
        return floor_hz, ref_db

    band_freqs = freq_hz[band_mask]
    band_spls = spl_db[band_mask]

    # Find first point in band where SPL >= threshold
    above_mask = band_spls >= threshold
    if not np.any(above_mask):
        # Never exceeds threshold — floor is lowest band frequency
        floor_hz = float(band_freqs[0])
        return floor_hz, ref_db

    first_above_idx = int(np.argmax(above_mask))  # index within the band mask

    # Check if this is the very first measurement point in the band
    if first_above_idx == 0:
        # First point in band is already above threshold — this means the
        # subwoofer extends cleanly with no pronounced low-frequency rolloff.
        # Floor is that first frequency.
        floor_hz = float(band_freqs[0])
        return floor_hz, ref_db

    # Otherwise the response entered the above-threshold region from below.
    # The floor is the frequency where it crossed up.
    floor_hz = float(band_freqs[first_above_idx])
    return floor_hz, ref_db


def generate_subwoofer_target(
    freq_hz: np.ndarray,
    spl_db: np.ndarray,
    params: TargetCurveParams,
    ref_db: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate a subwoofer target curve with LPF shaping.

    Below LF floor: smooth taper (modelled HPF-style, gentle slope).
    LF floor to 80 Hz: flat shelf at shelf_gain dB above ref level.
    At 80 Hz: anchor to ref_db (natural MLP alignment — no perceived
        level change at crossover).

    The output is 1/3-octave smoothed.

    Args:
        freq_hz: Measured frequency bins for the subwoofer (Hz).
        spl_db: Measured SPL values in dB.
        params: TargetCurveParams with lf_floor_threshold_db and shelf_gain.
        ref_db: Reference mid-bass level from detect_lf_floor().

    Returns:
        Tuple of (target_freq, target_spl) aligned to TARGET_FREQUENCIES.
    """
    # Detect LF floor from the measured response
    floor_hz, _ = detect_lf_floor(
        freq_hz, spl_db, threshold_db=params.lf_floor_threshold_db
    )

    # Interpolate measured response onto TARGET_FREQUENCIES
    measured_interp = np.interp(
        TARGET_FREQUENCIES, freq_hz, spl_db, left=np.nan, right=np.nan
    )

    # Start target at ref_db + shelf_gain (the shelf level)
    # Absolute shelf: from measured ref + shelf_gain (base level)
    # target_spl_db shifts the entire target upward (for absolute SPL calibration)
    if params.target_spl_db is not None:
        target_spl = params.target_spl_db
    else:
        target_spl = ref_db
    shelf_level = target_spl + params.shelf_gain
    target = np.full_like(TARGET_FREQUENCIES, shelf_level, dtype=float)

    # Above crossover: blend from shelf_level down to target_spl (absolute midrange)
    # This connects the subwoofer shelf to the speaker target at crossover.
    crossover = params.crossover_freq
    above_crossover = TARGET_FREQUENCIES > crossover
    if np.any(above_crossover):
        crossover_idx = int(np.argmax(above_crossover))
        for i in range(crossover_idx, len(TARGET_FREQUENCIES)):
            t = (i - crossover_idx) / max(1, len(TARGET_FREQUENCIES) - crossover_idx - 1)
            target[i] = target_spl + (shelf_level - target_spl) * (1.0 - t)

    # Below floor: apply smooth taper from shelf_level down to near ref_db
    # Model a gentle HPF slope below the detected floor
    below_floor = TARGET_FREQUENCIES < floor_hz
    if np.any(below_floor):
        log_floor = np.log10(floor_hz)
        log_min = np.log10(TARGET_FREQUENCIES[below_floor][0]) if np.any(below_floor) else log_floor
        log_range = log_floor - log_min if log_floor != log_min else 1.0
        for i, freq in enumerate(TARGET_FREQUENCIES):
            if freq < floor_hz:
                t = (np.log10(freq) - log_min) / log_range  # 0 at bottom, 1 at floor
                t = max(0.0, min(1.0, t))
                # Taper from shelf_level at floor to target_spl at bottom
                target[i] = target_spl + (shelf_level - target_spl) * t

    # Apply 1/3-octave smoothing
    # Apply subwoofer reference offset (for calibration)
    if params.subwoofer_ref_offset_db != 0.0:
        target = target + params.subwoofer_ref_offset_db

    target = smooth_curve(TARGET_FREQUENCIES, target, params.smoothing_octave_final)

    return TARGET_FREQUENCIES.copy(), target


def generate_all_subwoofer_targets(
    channel_responses: list[dict[str, Any]] | dict[str, Any],
    params: TargetCurveParams,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Generate separate target curves for SW1 and SW2.

    Uses MLP-only (position 0) for each subwoofer. Does NOT combine
    or average SW1 and SW2 — each gets its own target based on its
    own measured response.

    Args:
        channel_responses: Dict mapping sw_id -> {
            'positions': {
                '0': {'freq_hz': np.ndarray, 'spl_db': np.ndarray}
            }
        }. Keys not in SUBWOOFER_IDS are ignored.
        params: TargetCurveParams instance.

    Returns:
        Dict mapping sw_id -> (freq_hz, spl_db) target curve tuple.
    """
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    # Normalize list input to dict
    if isinstance(channel_responses, list):
        channel_dict_norm: dict[str, Any] = {}
        for c in channel_responses:
            cid = c.get("commandId", "")
            if cid:
                channel_dict_norm[cid.lower()] = c
        channel_responses = channel_dict_norm

    for sw_id, channel_data in channel_responses.items():
        if sw_id.lower() not in SUBWOOFER_IDS:
            continue

        positions = channel_data.get("positions", {})
        pos_0 = positions.get("0")
        if pos_0 is None:
            continue

        freq_hz = np.asarray(pos_0["freq_hz"])
        spl_db = np.asarray(pos_0["spl_db"])

        # Detect the floor and reference from MLP position 0
        floor_hz, ref_db = detect_lf_floor(
            freq_hz, spl_db, threshold_db=params.lf_floor_threshold_db
        )

        target_freq, target_spl = generate_subwoofer_target(
            freq_hz, spl_db, params, ref_db
        )

        result[sw_id.lower()] = (target_freq, target_spl)

    return result


def export_subwoofer_target(
    freq: np.ndarray,
    target_db: np.ndarray,
    output_dir: str | Path,
    sw_id: str,
) -> bool:
    """Write a subwoofer target curve to ``{sw_id}_target.frd``.

    Uses the same format as export_channel_frd(): one line per
    frequency bin in ascending order: ``<frequency_hz> <spl_db>``.

    Args:
        freq: Frequency bins in Hz.
        target_db: Target SPL values in dB (same length as freq).
        output_dir: Directory to write the .frd file into. Created if needed.
        sw_id: Subwoofer identifier, e.g. "sw1" or "sw2".
            The output filename will be ``{sw_id}_target.frd``.

    Returns:
        True on success, False on error.
    """
    return rew_exporter.export_channel_frd(freq, target_db, output_dir, f"{sw_id}_target")


def push_subwoofer_target_via_api(
    sw_id: str,
    freq: np.ndarray,
    target_db: np.ndarray,
    host: str = REW_API_DEFAULT_HOST,
    port: int = REW_API_DEFAULT_PORT,
) -> bool:
    """Push a subwoofer target curve to REW via the frequency response API.

    Uses POST /import/frequency-response-data (same endpoint as
    push_frequency_response_via_api). Each subwoofer is pushed as a
    separate API call.

    Args:
        sw_id: Subwoofer identifier, e.g. "sw1" or "sw2".
            Used as the REW curve identifier: ``{sw_id}_target``.
        freq: Frequency bins in Hz.
        target_db: Target SPL values in dB (same length as freq).
        host: REW API host. Default: "localhost".
        port: REW API port. Default: 4735.

    Returns:
        True when REW accepts the data (HTTP 2xx). False otherwise.
    """
    return rew_exporter.push_frequency_response_via_api(
        freq_hz=list(freq),
        spl_db=list(target_db),
        channel_name=f"{sw_id}_target",
        host=host,
        port=port,
    )


# -----------------------------------------------------------------------------
# Story 2 — Speaker HPF Shaping + Merged Target Curve
# -----------------------------------------------------------------------------

def detect_lf_cutoff(
    freq_hz: np.ndarray,
    spl_db: np.ndarray,
    threshold_db: float = 12.0,
) -> tuple[float, float]:
    """Detect speaker LF cutoff from measured response.

    Uses the 200–500 Hz window as the midrange reference band.
    Reference = mean SPL in 200–500 Hz band.
    Cutoff = lowest frequency in that band where smoothed SPL first drops
    BELOW (ref_db - threshold_db). If no point in the band is below threshold,
    returns the lowest frequency in the band (indicating a full-range speaker).

    Args:
        freq_hz: Measured frequency bins (Hz).
        spl_db: Measured SPL values in dB (same length as freq_hz).
        threshold_db: dB below the reference band average to search for the cutoff.

    Returns:
        Tuple of (cutoff_hz, ref_db) where cutoff_hz is the detected LF cutoff
        in Hz, and ref_db is the midrange reference level.
    """
    # Smooth response with 1/3-octave to remove narrow room effects
    smoothed = smooth_curve(freq_hz, spl_db, octave_bw=1.0 / 3.0)

    # Reference: mean SPL in 200–500 Hz band
    band_mask = (freq_hz >= 200.0) & (freq_hz <= 500.0)
    if not np.any(band_mask):
        ref_db = float(np.mean(spl_db))
        return float(freq_hz[0]) if len(freq_hz) > 0 else 0.0, ref_db

    band_freqs = freq_hz[band_mask]
    band_spls = smoothed[band_mask]
    ref_db = float(np.mean(band_spls))

    threshold = ref_db - threshold_db

    # Walk ascending through the 200–500 Hz band
    for i in range(len(band_freqs)):
        if band_spls[i] < threshold:
            return float(band_freqs[i]), ref_db

    # No point fell below threshold — full-range speaker
    return float(band_freqs[0]), ref_db


def generate_speaker_target(
    freq_hz: np.ndarray,
    spl_db: np.ndarray,
    params: TargetCurveParams,
    cutoff_hz: float,
    ref_db: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate HPF-shaped target for a speaker.

    Algorithm:
    1. Interpolate measured response to TARGET_FREQUENCIES grid.
    2. Below cutoff: HPF-style taper, never above measured SPL (prevents over-correction).
    3. Between cutoff and tilt_start_hz: flat at ref_db.
    4. Above tilt_start_hz: Harman HF tilt.
    5. 1/3-octave smoothing on output.

    Args:
        freq_hz: Measured frequency bins for the speaker (Hz).
        spl_db: Measured SPL values in dB.
        params: TargetCurveParams with hpf_cutoff_threshold_db, tilt_start_hz,
            tilt_rate, smoothing_octave_final settings.
        cutoff_hz: LF cutoff from detect_lf_cutoff().
        ref_db: Midrange reference level from detect_lf_cutoff().


    Returns:
        Tuple of (freq, target_db) aligned to TARGET_FREQUENCIES.
    """
    # Interpolate measured response onto TARGET_FREQUENCIES
    measured_interp = np.interp(
        TARGET_FREQUENCIES, freq_hz, spl_db, left=np.nan, right=np.nan
    )

    # Target SPL at midrange (absolute level for house curve)
    # Use target_spl_db if set, otherwise fall back to ref_db
    if params.target_spl_db is not None:
        target_spl_val = params.target_spl_db
    else:
        target_spl_val = ref_db

    # Start target: flat at target_spl_val (absolute SPL at midrange)
    target = np.full_like(TARGET_FREQUENCIES, target_spl_val, dtype=float)

    # Below cutoff: HPF taper from target_spl_val down to target_spl_val - hpf_shelf_gain
    hpf_gain = getattr(params, 'hpf_shelf_gain', 12.0)
    below_cutoff = TARGET_FREQUENCIES < cutoff_hz
    if np.any(below_cutoff):
        bottom_freq = float(TARGET_FREQUENCIES[below_cutoff][0])
        log_bottom = np.log10(bottom_freq)
        log_cutoff = np.log10(cutoff_hz)
        log_range = log_cutoff - log_bottom
        if log_range <= 0:
            log_range = 1.0
        for i, freq in enumerate(TARGET_FREQUENCIES):
            if freq >= cutoff_hz or np.isnan(measured_interp[i]):
                continue
            t = (np.log10(freq) - log_bottom) / log_range
            t = max(0.0, min(1.0, t))
            tapered = (target_spl_val - hpf_gain) + hpf_gain * t
            # Target must not exceed measured (prevents over-correction)
            target[i] = min(tapered, float(measured_interp[i]))

    # Apply 1/3-octave smoothing to the full target
    target = smooth_curve(TARGET_FREQUENCIES, target, params.smoothing_octave_final)

    # Above tilt_start_hz: Harman HF tilt
    target = apply_hf_tilt(
        TARGET_FREQUENCIES,
        target,
        start_hz=params.tilt_start_hz,
        tilt_rate=params.tilt_rate,
    )

    # Enforce: target must not exceed measured (prevents over-correction
    # below cutoff where 1/3-octave smoothing can introduce overshoot)
    for i in range(len(target)):
        if not np.isnan(measured_interp[i]) and target[i] > measured_interp[i] + 0.01:
            target[i] = measured_interp[i]
            # Spread to neighbors for smooth transitions
            for j in range(max(0, i - 1), min(len(target), i + 2)):
                if not np.isnan(measured_interp[j]) and target[j] > measured_interp[j] + 0.01:
                    target[j] = measured_interp[j]

    return TARGET_FREQUENCIES.copy(), target


def generate_all_speaker_targets(
    channel_freq_responses: list[dict[str, Any]],
    params: TargetCurveParams,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Generate per-speaker HPF targets for FL, C, FR.

    Args:
        channel_freq_responses: List of channel frequency response dicts from
            get_all_channels_freq_response(). Each entry has:
            - commandId: str
            - positions: {pos_key: {freq_hz, spl_db}}
            - averaged: {freq_hz, spl_db}
        params: TargetCurveParams instance.

    Returns:
        Dict mapping commandId (lowercase) -> (freq_hz, target_db) tuple.
        Only MAIN_CHANNEL_IDS (FL, C, FR) are processed.
    """
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for channel in channel_freq_responses:
        cmd_id_raw = channel.get("commandId", "")
        cmd_id = cmd_id_raw.lower()

        if cmd_id not in MAIN_CHANNEL_IDS:
            continue

        averaged = channel.get("averaged")
        if averaged is None:
            continue

        freq_hz = np.asarray(averaged["freq_hz"])
        spl_db = np.asarray(averaged["spl_db"])

        # Detect LF cutoff
        cutoff_hz, ref_db = detect_lf_cutoff(
            freq_hz, spl_db, threshold_db=params.hpf_cutoff_threshold_db
        )

        # Generate HPF target
        target_freq, target_db = generate_speaker_target(
            freq_hz, spl_db, params, cutoff_hz, ref_db
        )

        result[cmd_id] = (target_freq, target_db)

    return result


def export_speaker_target(
    freq: np.ndarray,
    target_db: np.ndarray,
    output_dir: str | Path,
    speaker_id: str,
) -> bool:
    """Write a speaker target curve to ``{speaker_id}_target.frd``.


    Args:
        freq: Frequency bins in Hz.
        target_db: Target SPL values in dB.
        output_dir: Directory to write the .frd file into.
        speaker_id: Speaker identifier (e.g. "fl", "c", "fr").

            Output filename: ``{speaker_id}_target.frd``.

    Returns:
        True on success, False on error.
    """
    return rew_exporter.export_channel_frd(freq, target_db, output_dir, f"{speaker_id}_target")


def push_speaker_target_via_api(
    speaker_id: str,
    freq: np.ndarray,
    target_db: np.ndarray,
    host: str = REW_API_DEFAULT_HOST,
    port: int = REW_API_DEFAULT_PORT,
) -> bool:
    """Push a speaker target curve to REW via the frequency response API.

    Args:
        speaker_id: Speaker identifier (e.g. "fl", "c", "fr").
            REW curve name: ``{speaker_id}_target``.
        freq: Frequency bins in Hz.
        target_db: Target SPL values in dB.
        host: REW API host. Default: "localhost".
        port: REW API port. Default: 4735.

    Returns:
        True when REW accepts the data (HTTP 2xx). False otherwise.
    """
    return rew_exporter.push_frequency_response_via_api(
        freq_hz=list(freq),
        spl_db=list(target_db),
        channel_name=f"{speaker_id}_target",
        host=host,
        port=port,
    )


# -----------------------------------------------------------------------------
# Merged Target Curve
# -----------------------------------------------------------------------------
def generate_house_curve(
    channel_responses: list[dict[str, Any]] | dict[str, Any],
    params: TargetCurveParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate the complete house curve from speaker + subwoofer measurements.

    The house curve is the single target that REW applies globally for EQ.
    It is built from BOTH the subwoofer (deep bass) and the speakers
    (midrange + treble), blended smoothly at the crossover frequency.

    Algorithm:
    1. Speaker targets (FL/C/FR): HPF-shaped per-channel, flat midrange, HF tilt.
    2. Subwoofer targets (SW1/SW2): MLP-only, LPF-shaped bass shelf with
       absolute SPL from target_spl_db (or measured reference).
    3. Merge subwoofers: average SW1 + SW2 for a single subwoofer curve.
    4. Merge speakers: arithmetic mean of FL + C + FR for a single speaker curve.
    5. Blend subwoofer and speaker curves at crossover_freq with smooth
       log-frequency crossover (+/- blend_octaves).

    Below xf_low: subwoofer dominates (deep bass)
    Above xf_high: speaker dominates (midrange + treble)
    Between xf_low and xf_high: smooth log-freq blend.

    Args:
        channel_responses: Full channel_responses from ady_parser.
        params: TargetCurveParams. Uses defaults if None.

    Returns:
        Tuple of (TARGET_FREQUENCIES, house_curve_db).
    """
    if params is None:
        params = TargetCurveParams()

    crossover = params.crossover_freq
    blend = params.blend_octaves
    xf_low = crossover / (2.0 ** blend)
    xf_high = crossover * (2.0 ** blend)

    # Per-channel speaker targets (FL/C/FR)
    speaker_targets = generate_all_speaker_targets(channel_responses, params)

    # Per-channel subwoofer targets (SW1/SW2)
    subwoofer_targets = generate_all_subwoofer_targets(channel_responses, params)

    if not speaker_targets and not subwoofer_targets:
        return np.array([], dtype=float), np.array([], dtype=float)

    # Single subwoofer curve: average SW1 + SW2
    if subwoofer_targets:
        sw_matrices = [np.asarray(t[1]) for t in subwoofer_targets.values()]
        sw_merged = np.mean(np.vstack(sw_matrices), axis=0)
    else:
        sw_merged = None

    # Single speaker curve: average FL + C + FR
    if speaker_targets:
        spk_matrices = [np.asarray(t[1]) for t in speaker_targets.values()]
        spk_merged = np.mean(np.vstack(spk_matrices), axis=0)
    else:
        spk_merged = None

    # Build house curve with smooth log-frequency crossover blend
    house = np.zeros_like(TARGET_FREQUENCIES, dtype=float)
    if sw_merged is not None and spk_merged is not None:
        for i, f in enumerate(TARGET_FREQUENCIES):
            if f < xf_low:
                house[i] = sw_merged[i]
            elif f > xf_high:
                house[i] = spk_merged[i]
            else:
                t = (np.log10(f / xf_low) / np.log10(xf_high / xf_low))
                t = max(0.0, min(1.0, t))
                house[i] = sw_merged[i] * (1.0 - t) + spk_merged[i] * t
    elif sw_merged is not None:
        house = sw_merged.copy()
    else:
        house = spk_merged.copy()

    house = smooth_curve(TARGET_FREQUENCIES, house, params.smoothing_octave_final)
    return TARGET_FREQUENCIES.copy(), house


def generate_merged_target(
    speaker_targets: dict[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Generate an averaged house curve from FL+C+FR per-speaker targets.

    Algorithm:
    1. All input targets are already on the TARGET_FREQUENCIES grid.
    2. Arithmetic mean across all available speakers at each freq point.
    3. If only 1 speaker available: return that speaker's target directly.
    4. If empty: return (empty, empty).

    Args:
        speaker_targets: Dict mapping commandId -> (freq, target_db).

    Returns:
        Tuple of (TARGET_FREQUENCIES, merged_target_db).
    """
    if not speaker_targets:
        return np.array([], dtype=float), np.array([], dtype=float)

    cmd_ids = list(speaker_targets.keys())
    if len(cmd_ids) == 1:
        freq, target_db = speaker_targets[cmd_ids[0]]
        return freq.copy(), target_db.copy()

    # Stack all target_db arrays into a matrix (rows=speakers)
    matrices = []
    for cmd_id in cmd_ids:
        _, target_db = speaker_targets[cmd_id]
        matrices.append(np.asarray(target_db))

    matrix = np.vstack(matrices)  # shape: (n_speakers, n_freqs)
    merged_db = np.mean(matrix, axis=0)

    return TARGET_FREQUENCIES.copy(), merged_db



def export_merged_target(
    freq: np.ndarray,
    merged_db: np.ndarray,
    output_dir: str | Path,
) -> bool:
    """Write a merged target curve to ``merged_target.frd``.


    Args:
        freq: Frequency bins in Hz.
        merged_db: Merged target SPL values in dB.
        output_dir: Directory to write the .frd file into.


    Returns:
        True on success, False on error.
    """
    return rew_exporter.export_channel_frd(freq, merged_db, output_dir, "merged_target")



def push_merged_target_via_api(
    freq: np.ndarray,
    merged_db: np.ndarray,
    host: str = REW_API_DEFAULT_HOST,
    port: int = REW_API_DEFAULT_PORT,
) -> bool:
    """Push merged target to REW via the house curve API.

    Tries /eq/house-curve first (the correct endpoint for house curves).
    Falls back to /import/frequency-response-data if that fails.

    Args:
        freq: Frequency bins in Hz.
        merged_db: Merged target SPL values in dB.
        host: REW API host. Default: "localhost".
        port: REW API port. Default: 4735.


    Returns:
        True when REW accepts the data (HTTP 2xx). False otherwise.
    """
    url_primary = f"http://{host}:{port}/eq/house-curve"
    frequency_list = [float(x) for x in np.asarray(freq).flatten()]
    level_list = [float(x) for x in np.asarray(merged_db).flatten()]

    payload = {
        "FrequencyResponseData": {
            "frequency": frequency_list,
            "level": level_list,
        }
    }
    body = json.dumps(payload).encode("utf-8")

    def try_push(url: str) -> bool:
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status in (200, 202)
        except Exception:
            return False

    if try_push(url_primary):
        return True

    # Fall back to the generic frequency response endpoint
    return rew_exporter.push_frequency_response_via_api(
        freq_hz=list(freq),
        spl_db=list(merged_db),
        channel_name="merged_target",
        host=host,
        port=port,
    )


