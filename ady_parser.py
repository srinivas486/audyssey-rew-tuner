"""ADY file parser for Audyssey MultEQ Editor exports.

ADY files are renamed JSON files exported from the Audyssey MultEQ Editor app.
This module provides loading and validation of ADY files, plus FFT-based
frequency response extraction from time-domain impulse response data.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np


class ADYParseError(Exception):
    """Raised when ADY file parsing fails."""
    pass


class ADYValidationError(ADYParseError):
    """Raised when ADY file content is invalid."""
    pass


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 48000  # Hz
"""Standard Audyssey measurement sample rate."""

EPS = 1e-12
"""Small constant to prevent log(0) in dB conversion."""


# -----------------------------------------------------------------------------
# File loading
# -----------------------------------------------------------------------------

def load_ady(path: str | Path) -> dict[str, Any]:
    """Load an ADY file and return its parsed JSON content.

    Args:
        path: Path to the .ady file.

    Returns:
        Parsed JSON content as a dictionary.

    Raises:
        ADYParseError: If the file cannot be read or parsed as JSON.
        ADYValidationError: If the JSON lacks required structure.
    """
    path = Path(path)

    if not path.exists():
        raise ADYParseError(f"ADY file not found: {path}")

    if path.suffix.lower() != '.ady':
        raise ADYParseError(f"Not an ADY file (expected .ady extension): {path}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ADYParseError(f"Invalid JSON in ADY file {path}: {e}") from e
    except OSError as e:
        raise ADYParseError(f"Failed to read ADY file {path}: {e}") from e

    if not isinstance(data, dict):
        raise ADYValidationError(
            f"ADY file {path} root must be a JSON object, got {type(data).__name__}"
        )

    channels_key = _find_key(data, 'detectedChannels')
    if channels_key is None:
        raise ADYValidationError(
            f"ADY file {path} is missing 'detectedChannels' field"
        )

    detected_channels = data[channels_key]
    if not isinstance(detected_channels, list):
        raise ADYValidationError(
            f"'detectedChannels' must be an array, got {type(detected_channels).__name__}"
        )

    return data


# -----------------------------------------------------------------------------
# Channel extraction
# -----------------------------------------------------------------------------

def get_channels(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the list of channel objects from parsed ADY data.

    Args:
        data: Parsed ADY content from load_ady().

    Returns:
        List of channel dictionaries.

    Raises:
        ADYValidationError: If the data structure is invalid.
    """
    channels_key = _find_key(data, 'detectedChannels')
    if channels_key is None:
        raise ADYValidationError("ADY data missing 'detectedChannels' field")

    channels = data[channels_key]

    if not isinstance(channels, list):
        raise ADYValidationError(
            f"'detectedChannels' must be an array, got {type(channels).__name__}"
        )

    if len(channels) == 0:
        warnings.warn("ADY file has no detected channels (empty detectedChannels array)")

    return channels


def get_channel_ids(channels: list[dict[str, Any]]) -> list[str]:
    """Extract CommandID values from a list of channel objects.

    Args:
        channels: List of channel dictionaries from get_channels().

    Returns:
        List of commandId strings.
    """
    ids = []
    for ch in channels:
        cmd_id = ch.get('commandId') or ch.get('CommandID')
        if cmd_id is not None:
            ids.append(cmd_id)
    return ids


def get_response_data(channel: dict[str, Any]) -> dict[str, list[float]]:
    """Extract responseData dict from a channel object.

    Args:
        channel: Channel dictionary from get_channels().

    Returns:
        The responseData dict mapping position index (str) to sample arrays.
    """
    return channel.get('responseData', {})


def get_measurement_positions(channel: dict[str, Any]) -> list[str]:
    """Return the list of measurement position indices for a channel.

    Args:
        channel: Channel dictionary from get_channels().

    Returns:
        List of position keys (e.g. ["0", "1", "2"]).
    """
    rd = get_response_data(channel)
    return list(rd.keys())


# -----------------------------------------------------------------------------
# FFT frequency response
# -----------------------------------------------------------------------------

def get_frequency_response(
    impulse_samples: list[float] | np.ndarray,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute frequency response from a time-domain impulse response via FFT.

    Args:
        impulse_samples: Time-domain impulse response (list or array of float64).
            Expected length: 16384 samples (from Audyssey measurements).
        sample_rate: Sample rate in Hz. Default: 48000.

    Returns:
        A tuple of (freq_hz, spl_db) where:
            - freq_hz: array of frequency bin centers (Hz), shape (N//2+1,)
            - spl_db: array of magnitude response in dB SPL, shape (N//2+1,)
    """
    samples = np.asarray(impulse_samples, dtype=np.float64)
    n = len(samples)

    # Real FFT — only positive frequencies
    fft_result = np.fft.rfft(samples)

    # Frequency axis: cycles per second (Hz)
    freq_hz = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    # Magnitude (linear)
    magnitude = np.abs(fft_result)

    # Convert to dB SPL (relative, with floor to avoid log(0))
    spl_db = 20.0 * np.log10(magnitude + EPS)

    return freq_hz, spl_db


def get_channel_freq_response(
    channel: dict[str, Any],
    sample_rate: float = DEFAULT_SAMPLE_RATE,
) -> dict[str, Any]:
    """Compute frequency response for all measurement positions of a channel.

    For channels with multiple positions, the SPL spectra are averaged in dB
    (logarithmic averaging is standard for SPL measurements).

    Args:
        channel: Channel dictionary from get_channels().
        sample_rate: Sample rate in Hz. Default: 48000.

    Returns:
        Dict with keys:
            - commandId (str): speaker/channel identifier
            - positions (dict): maps position key (str) to
                {"freq_hz": np.ndarray, "spl_db": np.ndarray}
            - averaged (dict): {"freq_hz": np.ndarray, "spl_db": np.ndarray}
              (average of all positions, in dB)
    """
    cmd_id = channel.get('commandId') or channel.get('CommandID', 'UNKNOWN')
    response_data = get_response_data(channel)
    position_keys = list(response_data.keys())

    if not position_keys:
        return {
            "commandId": cmd_id,
            "positions": {},
            "averaged": {"freq_hz": np.array([]), "spl_db": np.array([])},
        }

    # Compute FFT for each position
    position_results: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for pos_key in position_keys:
        samples = response_data[pos_key]
        freq_hz, spl_db = get_frequency_response(samples, sample_rate=sample_rate)
        position_results[pos_key] = (freq_hz, spl_db)

    # Average across positions in dB (logarithmic mean)
    # Use the first position's frequency axis as reference
    ref_freq = position_results[position_keys[0]][0]
    avg_spl = np.zeros_like(ref_freq)

    for pos_key in position_keys:
        avg_spl += position_results[pos_key][1]

    avg_spl = avg_spl / len(position_keys)

    return {
        "commandId": cmd_id,
        "positions": {
            pos_key: {"freq_hz": freq, "spl_db": spl_db}
            for pos_key, (freq, spl_db) in position_results.items()
        },
        "averaged": {"freq_hz": ref_freq, "spl_db": avg_spl},
    }


def get_all_channels_freq_response(
    data: dict[str, Any],
    sample_rate: float = DEFAULT_SAMPLE_RATE,
) -> list[dict[str, Any]]:
    """Compute frequency responses for all channels in an ADY dataset.

    Args:
        data: Parsed ADY content from load_ady().
        sample_rate: Sample rate in Hz. Default: 48000.

    Returns:
        List of channel frequency response dicts (see get_channel_freq_response).
    """
    channels = get_channels(data)
    return [get_channel_freq_response(ch, sample_rate=sample_rate) for ch in channels]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _find_key(data: dict[str, Any], target: str) -> str | None:
    """Case-insensitive key lookup in a dictionary."""
    target_lower = target.lower()
    for k in data.keys():
        if k.lower() == target_lower:
            return k
    return None


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def parse_and_summarize(path: str | Path) -> None:
    """Load an ADY file and print a summary of its contents.

    Args:
        path: Path to the .ady file.

    Raises:
        ADYParseError: If loading or validation fails.
    """
    data = load_ady(path)
    channels = get_channels(data)
    channel_ids = get_channel_ids(channels)

    print(f"Successfully parsed ADY file: {path}")
    print(f"  Detected channels: {len(channels)}")
    print(f"  Channel IDs: {', '.join(channel_ids)}")

    # Show measurement positions per channel
    for ch in channels:
        cmd_id = ch.get('commandId') or ch.get('CommandID', '?')
        positions = get_measurement_positions(ch)
        print(f"  {cmd_id}: {len(positions)} position(s) -> {positions}")

    if len(channels) == 0:
        warnings.warn("WARNING: No channels detected in this ADY file")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ady_parser.py <path-to.ady>")
        sys.exit(1)

    parse_and_summarize(sys.argv[1])