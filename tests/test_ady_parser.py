"""Tests for ady_parser module."""

import json
import tempfile
import warnings
from pathlib import Path

import pytest

from ady_parser import (
    ADYParseError,
    ADYValidationError,
    get_channel_ids,
    get_channels,
    load_ady,
    parse_and_summarize,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def valid_ady_data():
    """Return a minimal valid ADY structure matching the Audyssey format."""
    return {
        "detectedChannels": [
            {
                "commandId": "FL",
                "responseData": {
                    "0": [0.0004, 0.0005, 0.0006] * 100,
                    "1": [0.0003, 0.0004, 0.0005] * 100,
                },
            },
            {
                "commandId": "C",
                "responseData": {
                    "0": [0.0005, 0.0006, 0.0007] * 100,
                },
            },
            {
                "commandId": "FR",
                "responseData": {
                    "0": [0.0006, 0.0007, 0.0008] * 100,
                },
            },
        ]
    }


@pytest.fixture
def empty_channels_data():
    """Return ADY structure with empty detectedChannels array."""
    return {"detectedChannels": []}


@pytest.fixture
def missing_channels_data():
    """Return ADY structure without detectedChannels field."""
    return {"someOtherField": []}


@pytest.fixture
def ady_file(tmp_path, valid_ady_data):
    """Write valid_ady_data to a temp .ady file and return its Path."""
    f = tmp_path / "test.ady"
    f.write_text(json.dumps(valid_ady_data), encoding="utf-8")
    return f


# -----------------------------------------------------------------------------
# load_ady tests
# -----------------------------------------------------------------------------

class TestLoadAdy:
    def test_loads_valid_file(self, ady_file):
        """load_ady returns parsed dict for a valid ADY file."""
        data = load_ady(ady_file)
        assert isinstance(data, dict)
        assert "detectedChannels" in data

    def test_loads_pathlib_path(self, ady_file):
        """load_ady accepts a Path object."""
        data = load_ady(ady_file)
        assert isinstance(data, dict)

    def test_loads_str_path(self, ady_file):
        """load_ady accepts a string path."""
        data = load_ady(str(ady_file))
        assert isinstance(data, dict)

    def test_raises_on_nonexistent_file(self, tmp_path):
        """ADYParseError raised when file does not exist."""
        with pytest.raises(ADYParseError, match="not found"):
            load_ady(tmp_path / "does_not_exist.ady")

    def test_raises_on_wrong_extension(self, tmp_path):
        """ADYParseError raised when file doesn't have .ady extension."""
        f = tmp_path / "test.json"
        f.write_text("{}", encoding="utf-8")
        with pytest.raises(ADYParseError, match="expected .ady extension"):
            load_ady(f)

    def test_raises_on_invalid_json(self, tmp_path):
        """ADYParseError raised when file contains invalid JSON."""
        f = tmp_path / "test.ady"
        f.write_text("{ this is not json }", encoding="utf-8")
        with pytest.raises(ADYParseError, match="Invalid JSON"):
            load_ady(f)

    def test_raises_on_non_object_root(self, tmp_path):
        """ADYValidationError raised when root is not a JSON object."""
        f = tmp_path / "test.ady"
        f.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ADYValidationError, match="root must be a JSON object"):
            load_ady(f)

    def test_raises_on_missing_detected_channels(self, tmp_path, missing_channels_data):
        """ADYValidationError raised when detectedChannels is absent."""
        f = tmp_path / "test.ady"
        f.write_text(json.dumps(missing_channels_data), encoding="utf-8")
        with pytest.raises(ADYValidationError, match="missing 'detectedChannels'"):
            load_ady(f)

    def test_raises_on_non_array_detected_channels(self, tmp_path):
        """ADYValidationError raised when detectedChannels is not an array."""
        data = {"detectedChannels": {"0": []}}
        f = tmp_path / "test.ady"
        f.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ADYValidationError, match="must be an array"):
            load_ady(f)


# -----------------------------------------------------------------------------
# get_channels tests
# -----------------------------------------------------------------------------

class TestGetChannels:
    def test_returns_channel_list(self, valid_ady_data):
        """get_channels returns the list of channel dicts."""
        channels = get_channels(valid_ady_data)
        assert len(channels) == 3
        assert all(isinstance(ch, dict) for ch in channels)

    def test_warns_on_empty_channels(self, empty_channels_data):
        """Warning issued when detectedChannels is empty."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            channels = get_channels(empty_channels_data)
            assert channels == []
            assert len(w) == 1
            assert "no detected channels" in str(w[0].message).lower()

    def test_raises_on_missing_detected_channels(self, missing_channels_data):
        """ADYValidationError raised when detectedChannels is absent."""
        with pytest.raises(ADYValidationError, match="missing 'detectedChannels'"):
            get_channels(missing_channels_data)


# -----------------------------------------------------------------------------
# get_channel_ids tests
# -----------------------------------------------------------------------------

class TestGetChannelIds:
    def test_extracts_command_ids(self, valid_ady_data):
        """get_channel_ids returns list of commandId strings."""
        channels = get_channels(valid_ady_data)
        ids = get_channel_ids(channels)
        assert ids == ["FL", "C", "FR"]

    def test_handles_uppercase_command_id(self):
        """Handles CommandID (uppercase) in addition to commandId."""
        channels = [{"CommandID": "SW1", "responseData": {}}]
        ids = get_channel_ids(channels)
        assert ids == ["SW1"]

    def test_empty_list_for_no_channels(self):
        """Returns empty list when given empty channel list."""
        assert get_channel_ids([]) == []


# -----------------------------------------------------------------------------
# parse_and_summarize tests
# -----------------------------------------------------------------------------

class TestParseAndSummarize:
    def test_prints_summary(self, ady_file, capsys):
        """parse_and_summarize prints channel list to stdout."""
        parse_and_summarize(ady_file)
        captured = capsys.readouterr()
        assert "Successfully parsed" in captured.out
        assert "FL" in captured.out
        assert "C" in captured.out
        assert "FR" in captured.out

    def test_warns_on_empty_channels(self, tmp_path):
        """Warning issued when ADY file has no channels."""
        f = tmp_path / "empty.ady"
        f.write_text(json.dumps({"detectedChannels": []}), encoding="utf-8")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            parse_and_summarize(f)
            # Should have exactly one warning about empty channels
            channel_warnings = [x for x in w if "no detected channels" in str(x.message).lower()]
            assert len(channel_warnings) == 1

    def test_raises_parse_error(self, tmp_path):
        """Propagates ADYParseError on bad file."""
        with pytest.raises(ADYParseError):
            parse_and_summarize(tmp_path / "nonexistent.ady")


# -----------------------------------------------------------------------------
# Integration: use the real test.ady if present
# -----------------------------------------------------------------------------

class TestRealAdyFile:
    """Tests against the real test.ady file in the repo root."""

    def test_loads_real_test_ady(self):
        """Smoke test: load_ady works with the repo's test.ady."""
        real_path = Path(__file__).parent.parent / "test.ady"
        if not real_path.exists():
            pytest.skip("test.ady not present in repo root")

        data = load_ady(real_path)
        channels = get_channels(data)
        ids = get_channel_ids(channels)

        # Based on repo research, test.ady has 11 channels
        assert len(channels) == 11
        assert ids == ["FL", "C", "FR", "SLA", "SRA", "FDL", "FDR", "SDL", "SDR", "SW1", "SW2"]
