"""REW .frd exporter and REW API pusher.

Provides utilities to:
  1. Write frequency response data to REW-compatible .frd files.
  2. Push frequency response data to a running REW instance via its HTTP API.
"""

from __future__ import annotations

import base64
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

REW_API_DEFAULT_HOST = "localhost"
REW_API_DEFAULT_PORT = 4735


# -----------------------------------------------------------------------------
# Story 2.1 — Write REW .frd format per channel
# -----------------------------------------------------------------------------

def export_channel_frd(
    freq_hz: list[float] | tuple[float, ...] | Any,
    spl_db: list[float] | tuple[float, ...] | Any,
    output_dir: str | Path,
    channel_name: str,
) -> bool:
    """Write a frequency response curve to a REW .frd file.

    The .frd file format is one line per frequency bin::

        <frequency_hz> <spl_db>

    Frequencies are written in ascending order.

    Args:
        freq_hz: Frequency bin centers in Hz. Supports any sequence
            (list, tuple, numpy array, etc.).
        spl_db: Magnitude response in dB SPL. Must have the same length
            as ``freq_hz``.
        output_dir: Directory to write the .frd file into. Created if it
            does not exist.
        channel_name: Base name for the output file. The file will be named
            ``{output_dir}/{channel_name}.frd``.

    Returns:
        True on success. False if the output directory cannot be created
        or the file cannot be written.
    """
    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Convert any array-like to plain Python lists for safe file I/O
        freq_list = list(freq_hz)
        spl_list = list(spl_db)

        if len(freq_list) != len(spl_list):
            print(f"export_channel_frd: freq_hz and spl_db length mismatch "
                  f"({len(freq_list)} vs {len(spl_list)}) — skipping")
            return False

        if len(freq_list) == 0:
            print("export_channel_frd: empty data — skipping")
            return False

        # Pair and sort by frequency ascending
        pairs = sorted(zip(freq_list, spl_list), key=lambda p: p[0])

        file_path = output_path / f"{channel_name}.frd"
        with open(file_path, "w", encoding="utf-8") as f:
            for freq, spl in pairs:
                f.write(f"{freq} {spl}\n")

        return True

    except OSError as e:
        print(f"export_channel_frd: failed to write {channel_name}.frd: {e}")
        return False


# -----------------------------------------------------------------------------
# Story 2.2 — Push via REW API with graceful fallback
# -----------------------------------------------------------------------------

def push_frequency_response_via_api(
    freq_hz: list[float] | tuple[float, ...] | Any,
    spl_db: list[float] | tuple[float, ...] | Any,
    channel_name: str,
    host: str = REW_API_DEFAULT_HOST,
    port: int = REW_API_DEFAULT_PORT,
) -> bool:
    """POST frequency response data to a running REW instance.

    Sends a JSON payload to REW's ``/import/frequency-response-data`` endpoint::

        POST http://{host}:{port}/import/frequency-response-data
        Content-Type: application/json

        {
          "identifier": "FL",
          "isImpedance": false,
          "startFreq": 20.0,
          "freqStep": 0.5,
          "magnitude": "...base64 big-endian float32..."
        }

    Args:
        freq_hz: Frequency bin centers in Hz.
        spl_db: Magnitude response in dB SPL.
        channel_name: Identifier for this curve (appears in REW's UI).
        host: REW API host. Default: "localhost".
        port: REW API port. Default: 4735.

    Returns:
        True when REW accepts the data (HTTP 2xx). False when the connection
        is refused or REW returns an error. No exception is raised.
    """
    freq_list = list(freq_hz)
    spl_list = list(spl_db)

    if len(freq_list) != len(spl_list):
        print(f"push_frequency_response_via_api: freq_hz and spl_db length mismatch "
              f"({len(freq_list)} vs {len(spl_list)}) — skipping")
        return False

    if len(freq_list) == 0:
        print("push_frequency_response_via_api: empty data — skipping")
        return False

    # Compute linear frequency axis parameters
    # freq_hz is expected to be linearly spaced (rfft output: 0 to sample_rate/2)
    start_freq = float(freq_list[0])
    freq_step = float(freq_list[1] - freq_list[0]) if len(freq_list) > 1 else 0.0

    # Pack SPL values as big-endian float32, then base64-encode
    packed = struct.pack(f'>{len(spl_list)}f', *spl_list)  # '>' = big-endian
    magnitude_b64 = base64.b64encode(packed).decode('ascii')

    # REW's /import/frequency-response-data accepts a FrequencyResponseData
    # object directly at the root level — no "FrequencyResponseData" wrapper.
    #
    # Root-level fields (per REW API docs):
    #   identifier  — name for the resulting measurement
    #   isImpedance — false = SPL data (not impedance)
    #   startFreq   — first frequency bin (Hz)
    #   freqStep    — frequency step for linear-spaced data (Hz)
    #   magnitude   — base64 big-endian float32 array
    #   phase       — optional base64 big-endian float32 array (degrees)
    payload: dict[str, Any] = {
        "identifier": channel_name,
        "isImpedance": False,
        "startFreq": start_freq,
        "freqStep": freq_step,
        "magnitude": magnitude_b64,
    }

    import json

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
    except (TypeError, ValueError) as e:
        print(f"push_frequency_response_via_api: failed to serialise payload: {e}")
        return False

    # Resolve "localhost" to 127.0.0.1 to avoid IPv6 issues on macOS
    # (urllib tries ::1 first when resolving "localhost", causing connection refused)
    import socket
    if host in ("localhost", "127.0.0.1"):
        host = "127.0.0.1"
    url = f"http://{host}:{port}/import/frequency-response-data"

    # Debug: show what we're about to send (truncated magnitude for readability)
    print(f"REW API push to {url}")
    print(f"  payload: identifier={channel_name!r}, "
          f"startFreq={start_freq}, freqStep={freq_step:.6f}, "
          f"magnitude[0:40]={magnitude_b64[:40]!r}...")

    try:
        req = urllib.request.Request(
            url,
            data=data_bytes,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
    except urllib.error.URLError as e:
        # Connection refused or other network error
        print(f"REW API not available at {host}:{port} — skipping")
        return False
    except urllib.error.HTTPError as e:
        # REW responded but with an error code — show the actual response body
        body = e.read().decode('utf-8', errors='replace')
        print(f"REW API HTTP error {e.code} for channel {channel_name}: {body[:300]}")
        return False
    except OSError as e:
        # Some other socket / DNS error
        print(f"REW API not available at {host}:{port} — skipping")
        return False

    return 200 <= status < 300
