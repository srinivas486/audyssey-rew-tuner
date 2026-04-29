"""ADY file parser for Audyssey MultEQ Editor exports.

ADY files are renamed JSON files exported from the Audyssey MultEQ Editor app.
This module provides loading and validation of ADY files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ADYParseError(Exception):
    """Raised when ADY file parsing fails."""
    pass


class ADYValidationError(ADYParseError):
    """Raised when ADY file content is invalid."""
    pass


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

    if not path.suffix.lower() == '.ady':
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

    # Check for detectedChannels (case-insensitive key lookup)
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


def get_channels(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the list of channel objects from parsed ADY data.

    Args:
        data: Parsed ADY content from load_ady().

    Returns:
        List of channel dictionaries.

    Raises:
        ADYValidationError: If the data structure is invalid.
    """
    # Case-insensitive key lookup for detectedChannels
    channels_key = _find_key(data, 'detectedChannels')
    if channels_key is None:
        raise ADYValidationError("ADY data missing 'detectedChannels' field")

    channels = data[channels_key]

    if not isinstance(channels, list):
        raise ADYValidationError(
            f"'detectedChannels' must be an array, got {type(channels).__name__}"
        )

    if len(channels) == 0:
        import warnings
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
        # Support both lowercase 'commandId' and uppercase 'CommandID'
        cmd_id = ch.get('commandId') or ch.get('CommandID')
        if cmd_id is not None:
            ids.append(cmd_id)
    return ids


def _find_key(data: dict[str, Any], target: str) -> str | None:
    """Case-insensitive key lookup in a dictionary.

    Args:
        data: Dictionary to search.
        target: Key name to find (case-insensitive).

    Returns:
        The actual key if found, None otherwise.
    """
    target_lower = target.lower()
    for k in data.keys():
        if k.lower() == target_lower:
            return k
    return None


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

    if len(channels) == 0:
        import warnings
        warnings.warn("WARNING: No channels detected in this ADY file")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ady_parser.py <path-to.ady>")
        sys.exit(1)

    parse_and_summarize(sys.argv[1])
