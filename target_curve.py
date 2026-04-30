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
    """Generate 1/6-octave frequency grid from 20 Hz to 20 kHz."""
    log_min = np.log10(20.0)
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
    """Tunable parameters for target curve generation."""

    bass_shelf_gain: float = 6.0
    """dB of bass lift at 20 Hz, rolling off to 0 dB at bass_shelf_start."""

    bass_shelf_start: float = 80.0
    """Hz — frequency above which the bass shelf no longer applies."""

    tilt_start_hz: float = 3000.0
    """Hz — frequency above which high-frequency tilt begins."""

    tilt_rate: float = 1.5
    """dB/decade — high-frequency downward tilt rate."""

    mlp_weight: float = 2.0
    """Weight for MLP position (0) in the weighted average. Positions 1-7 get weight 1."""

    outlier_threshold_db: float = 10.0
    """dB — if a position deviates more than this from MLP at a frequency, exclude it."""

    smoothing_octave: float = 1.0 / 3.0
    """Octave bandwidth for smoothing (1/3 octave = standard REW smoothing)."""

    crossover_freq: float = 80.0
    """Hz — subwoofer/speaker crossover frequency (used for alignment)."""


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
) -> np.ndarray:
    """Apply a smooth bass shelf boost below start_hz.

    The boost at 20 Hz ≈ gain_db, rolling off to 0 dB at start_hz.
    Below 20 Hz, the 20 Hz value is held constant.

    Roll-off formula:
        shelfBoost(f) = gain_db * (1 - log10(f / start_hz) / log10(20 / start_hz))

    Args:
        freqs: Frequency array in Hz.
        spl: SPL values in dB.
        start_hz: Frequency above which no boost is applied.
        gain_db: dB boost at 20 Hz.

    Returns:
        New SPL array with bass shelf applied.
    """
    result = spl.copy()
    below_mask = freqs < start_hz
    if not np.any(below_mask):
        return result

    min_freq = max(freqs[below_mask].min(), 20.0)
    log_ratio = np.log10(20.0 / start_hz)

    for i, freq in enumerate(freqs):
        if freq >= start_hz:
            continue
        clamped_freq = max(freq, min_freq)
        t = 1.0 - np.log10(clamped_freq / start_hz) / log_ratio
        t = max(0.0, min(1.0, t))
        result[i] = spl[i] + gain_db * t

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
    """Generate a target curve from parsed ADY measurement data.

    Algorithm:
    1. For each main channel (FL, C, FR), compute MLP-weighted geometric mean
       across positions 0-7 with outlier rejection.
    2. Average the three MLP-weighted curves into a single target.
    3. Apply bass shelf boost below bass_shelf_start.
    4. Apply HF downward tilt above tilt_start_hz.
    5. Apply 1/3-octave smoothing.

    Args:
        data: Parsed ADY content from ady_parser.load_ady().
        params: Tunable parameters. Uses defaults if None.

    Returns:
        Tuple of (freq_hz, spl_db) arrays for the target curve.
    """
    if params is None:
        params = TargetCurveParams()

    # Import here to avoid circular dependency
    from ady_parser import get_all_channels_freq_response, get_channels

    channels = get_channels(data)
    channel_responses = get_all_channels_freq_response(data)

    # Build a lookup: commandId -> freq response dict
    response_lookup: dict[str, dict[str, Any]] = {}
    for ch_resp in channel_responses:
        cmd_id = ch_resp.get("commandId", "UNKNOWN")
        # Normalize to lowercase for matching
        response_lookup[cmd_id.lower()] = ch_resp
        response_lookup[cmd_id.upper()] = ch_resp

    target_curves: list[tuple[np.ndarray, np.ndarray]] = []

    for main_id in sorted(MAIN_CHANNEL_IDS):
        # Try various case/spelling variants
        ch_resp = (
            response_lookup.get(main_id)
            or response_lookup.get(main_id.upper())
            or response_lookup.get(main_id.lower())
        )
        if ch_resp is None:
            continue

        positions_data = ch_resp.get("positions", {})
        if not positions_data:
            continue

        # Get MLP (position 0) SPL interpolated to target frequencies
        if "0" not in positions_data:
            continue

        mlp_freq = positions_data["0"]["freq_hz"]
        mlp_spl_orig = positions_data["0"]["spl_db"]
        mlp_spl_interp = np.interp(TARGET_FREQUENCIES, mlp_freq, mlp_spl_orig, left=np.nan, right=np.nan)

        # Build list of [MLP_spl, pos1_spl, ..., pos7_spl]
        all_spl_arrays: list[np.ndarray] = [mlp_spl_interp]
        for pos in range(1, 8):
            pos_key = str(pos)
            if pos_key not in positions_data:
                continue
            pos_freq = positions_data[pos_key]["freq_hz"]
            pos_spl_orig = positions_data[pos_key]["spl_db"]
            pos_spl_interp = np.interp(TARGET_FREQUENCIES, mlp_freq, pos_spl_orig, left=np.nan, right=np.nan)
            all_spl_arrays.append(pos_spl_interp)

        # Apply outlier rejection
        mlp_list = list(mlp_spl_interp)
        all_lists = [list(a) for a in all_spl_arrays]
        accepted_lists, _ = _apply_outlier_rejection(mlp_list, all_lists, params.outlier_threshold_db)

        # Weighted geometric mean
        # MLP (index 0) gets weight = mlp_weight; all others get weight 1
        n_accepted = len(accepted_lists)
        if n_accepted == 0:
            continue

        weights = [params.mlp_weight] + [1.0] * (n_accepted - 1)

        channel_curve = np.zeros_like(TARGET_FREQUENCIES)
        for i in range(len(TARGET_FREQUENCIES)):
            spl_at_i = [pos[i] for pos in accepted_lists]
            w_at_i = weights[:len(spl_at_i)]
            channel_curve[i] = weighted_geometric_mean(spl_at_i, w_at_i)

        target_curves.append((TARGET_FREQUENCIES, channel_curve))

    if not target_curves:
        # Fallback: return flat curve
        return TARGET_FREQUENCIES.copy(), np.zeros_like(TARGET_FREQUENCIES)

    # Average across main channels (FL, C, FR)
    avg_curve = np.zeros_like(TARGET_FREQUENCIES)
    for _, spl_arr in target_curves:
        avg_curve += spl_arr
    avg_curve /= len(target_curves)

    # Apply bass shelf
    avg_curve = apply_bass_shelf(
        TARGET_FREQUENCIES, avg_curve,
        start_hz=params.bass_shelf_start,
        gain_db=params.bass_shelf_gain,
    )

    # Apply HF tilt
    avg_curve = apply_hf_tilt(
        TARGET_FREQUENCIES, avg_curve,
        start_hz=params.tilt_start_hz,
        tilt_rate=params.tilt_rate,
    )

    # Apply smoothing
    avg_curve = smooth_curve(TARGET_FREQUENCIES, avg_curve, params.smoothing_octave)

    return TARGET_FREQUENCIES.copy(), avg_curve


# -----------------------------------------------------------------------------
# File export
# -----------------------------------------------------------------------------

def export_target_curve_txt(
    freqs: np.ndarray,
    spl: np.ndarray,
    path: Path | str,
) -> bool:
    """Write a target curve to a plain-text REW house curve file.

    Format (one line per point, space-separated):
        <frequency_hz> <offset_db>

    Frequencies are written in ascending order.

    Args:
        freqs: Frequency array in Hz.
        spl: SPL/offset array in dB.
        path: Output file path.

    Returns:
        True on success, False on error.
    """
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        pairs = sorted(zip(freqs, spl), key=lambda p: p[0])
        with open(path, "w", encoding="utf-8") as f:
            for freq, offset in pairs:
                f.write(f"{freq:.4f} {offset:.4f}\n")
        return True
    except OSError as e:
        print(f"export_target_curve_txt: failed to write {path}: {e}")
        return False


# -----------------------------------------------------------------------------
# REW API: push house curve
# -----------------------------------------------------------------------------

def push_target_curve_via_api(
    path: Path | str,
    host: str = REW_API_DEFAULT_HOST,
    port: int = REW_API_DEFAULT_PORT,
) -> bool:
    """Tell REW to load a house curve file via the /eq/house-curve API.

    POST http://{host}:{port}/eq/house-curve
    Content-Type: application/json

    {"path": "/absolute/path/to/file.txt"}

    Args:
        path: Absolute path to the house curve .txt file.
        host: REW API host. Default: "localhost".
        port: REW API port. Default: 4735.

    Returns:
        True when REW accepts the request (HTTP 2xx), False on error.
    """
    resolved = str(Path(path).resolve())

    if host in ("localhost", "127.0.0.1"):
        host = "127.0.0.1"
    url = f"http://{host}:{port}/eq/house-curve"

    # Try all known formats: raw string, JSON with path key, form-encoded
    import json
    candidates = [
        # Candidate 1: raw path as plain string
        ("text/plain", resolved.encode("utf-8")),
        # Candidate 2: JSON object {"path": "/absolute/path"}
        ("application/json", json.dumps({"path": resolved}).encode("utf-8")),
        # Candidate 3: form-encoded path=...
        ("application/x-www-form-urlencoded", f"path={resolved}".encode("utf-8")),
    ]
    last_err = None
    for ctype, payload in candidates:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": ctype},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                print(f"  [✓] Target curve loaded into REW (HTTP {status}): {resolved}")
                return True
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
        except urllib.error.URLError as e:
            last_err = f"connection error: {e.reason}"
            break
        except OSError as e:
            last_err = f"connection error: {e}"
            break

    print(f"  [✗] REW house-curve API failed (tried all formats): {last_err}")
    return False
