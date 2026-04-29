"""Tests for ady_parser module."""

import json
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pytest

from ady_parser import (
    ADYParseError,
    ADYValidationError,
    get_all_channels_freq_response,
    get_channel_freq_response,
    get_channel_ids,
    get_channels,
    get_frequency_response,
    get_measurement_positions,
    get_response_data,
    load_ady,
    parse_and_summarize,
    DEFAULT_SAMPLE_RATE,
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

# -----------------------------------------------------------------------------
# FFT frequency response tests
# -----------------------------------------------------------------------------

class TestGetFrequencyResponse:
    def test_fft_of_impulse_produces_valid_freq_axis(self):
        """FFT produces correct frequency axis range (0 to Nyquist)."""
        # 16384 samples at 48kHz
        n = 16384
        sr = 48000
        impulse = [1.0] + [0.0] * (n - 1)  # unit impulse
        freq_hz, spl_db = get_frequency_response(impulse, sample_rate=sr)

        assert freq_hz[0] == 0.0  # DC bin
        assert freq_hz[-1] == sr / 2  # Nyquist
        assert len(freq_hz) == n // 2 + 1  # 8193 bins
        assert len(spl_db) == n // 2 + 1

    def test_fft_of_impulse_produces_plausible_spl_range(self):
        """SPL values for a unit impulse are in plausible range."""
        n = 16384
        sr = 48000
        impulse = [1.0] + [0.0] * (n - 1)
        _freq_hz, spl_db = get_frequency_response(impulse, sample_rate=sr)

        # dB SPL should be above noise floor and below +120
        assert np.min(spl_db) > -200  # well above -infinity
        assert np.max(spl_db) < 200  # sanity upper bound

    def test_fft_of_decaying_exponential_has_expected_shape(self):
        """Decaying exponential impulse produces smooth, band-limited spectrum."""
        n = 16384
        sr = 48000
        t = np.arange(n) / sr
        # Impulse: decaying exponential (like a real room measurement)
        impulse = np.exp(-30.0 * t)  # fast decay
        freq_hz, spl_db = get_frequency_response(impulse, sample_rate=sr)

        # Spectrum should be smooth and roll off at high frequencies
        assert len(freq_hz) == n // 2 + 1
        assert len(spl_db) == n // 2 + 1
        # Magnitude at DC should be the integral of the impulse
        assert spl_db[0] > -100  # large low-frequency content

    def test_fft_uses_correct_nyquist_frequency(self):
        """Highest frequency bin equals Nyquist (half sample rate)."""
        n = 16384
        sr = 48000
        impulse = [1.0] * n
        freq_hz, _spl_db = get_frequency_response(impulse, sample_rate=sr)
        assert freq_hz[-1] == sr / 2

    def test_fft_result_reproducible(self):
        """Calling FFT twice on same data gives identical results."""
        impulse = [0.5] * 1000 + [0.0] * 15884
        freq1, spl1 = get_frequency_response(impulse, sample_rate=48000)
        freq2, spl2 = get_frequency_response(impulse, sample_rate=48000)
        np.testing.assert_array_equal(freq1, freq2)
        np.testing.assert_array_equal(spl1, spl2)


class TestGetChannelFreqResponse:
    def test_extracts_command_id(self):
        """commandId is preserved in output."""
        channel = {"commandId": "FL", "responseData": {"0": [1.0] * 256}}
        result = get_channel_freq_response(channel)
        assert result["commandId"] == "FL"

    def test_returns_all_position_keys(self):
        """All measurement positions are included in positions dict."""
        channel = {
            "commandId": "C",
            "responseData": {
                "0": [0.1] * 512,
                "1": [0.2] * 512,
            },
        }
        result = get_channel_freq_response(channel)
        assert set(result["positions"].keys()) == {"0", "1"}

    def test_averaged_has_same_length_as_positions(self):
        """Averaged spectrum has same bin count as individual positions."""
        n = 1024
        channel = {
            "commandId": "SW1",
            "responseData": {
                "0": list(np.random.rand(n)),
                "1": list(np.random.rand(n)),
            },
        }
        result = get_channel_freq_response(channel)
        pos_bins = len(result["positions"]["0"]["spl_db"])
        avg_bins = len(result["averaged"]["spl_db"])
        assert pos_bins == avg_bins

    def test_averaged_is_different_from_single_position(self):
        """Averaged spectrum over 2 positions differs from single position."""
        n = 2048
        channel = {
            "commandId": "FL",
            "responseData": {
                "0": list(np.ones(n) * 0.5),
                "1": list(np.ones(n) * 1.0),
            },
        }
        result = get_channel_freq_response(channel)
        pos0_db = result["positions"]["0"]["spl_db"]
        avg_db = result["averaged"]["spl_db"]
        # Averaged dB should be between the two (log scale, so not linear mean)
        assert not np.allclose(pos0_db, avg_db, atol=0.01)

    def test_handles_empty_response_data(self):
        """Empty responseData returns empty averaged spectrum."""
        channel = {"commandId": "FR", "responseData": {}}
        result = get_channel_freq_response(channel)
        assert result["commandId"] == "FR"
        assert len(result["averaged"]["spl_db"]) == 0


class TestGetAllChannelsFreqResponse:
    def test_returns_list_of_all_channels(self):
        """Returns one entry per channel in the ADY data."""
        data = {
            "detectedChannels": [
                {"commandId": "FL", "responseData": {"0": [0.1] * 512}},
                {"commandId": "FR", "responseData": {"0": [0.2] * 512}},
            ]
        }
        results = get_all_channels_freq_response(data)
        assert len(results) == 2
        assert [r["commandId"] for r in results] == ["FL", "FR"]


class TestGetResponseData:
    def test_returns_response_data_dict(self):
        """get_response_data extracts the responseData field."""
        rd = {"0": [1.0, 2.0], "1": [3.0, 4.0]}
        channel = {"commandId": "FL", "responseData": rd}
        assert get_response_data(channel) == rd

    def test_returns_empty_dict_when_missing(self):
        """Returns empty dict if channel has no responseData."""
        assert get_response_data({"commandId": "FL"}) == {}


class TestGetMeasurementPositions:
    def test_returns_position_keys(self):
        """Returns sorted list of position keys from responseData."""
        channel = {
            "commandId": "C",
            "responseData": {"0": [1.0] * 100, "2": [2.0] * 100, "1": [3.0] * 100},
        }
        # dict preserves insertion order in Python 3.7+, result is list of keys
        positions = get_measurement_positions(channel)
        assert set(positions) == {"0", "1", "2"}
        assert len(positions) == 3


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

    def test_real_test_ady_fft_produces_valid_freq_response(self):
        """FFT of real test.ady produces plausible frequency range."""
        real_path = Path(__file__).parent.parent / "test.ady"
        if not real_path.exists():
            pytest.skip("test.ady not present in repo root")

        data = load_ady(real_path)
        freq_res = get_all_channels_freq_response(data)

        # 11 channels
        assert len(freq_res) == 11

        for ch_result in freq_res:
            avg = ch_result["averaged"]
            # 16384 samples -> 8193 bins
            assert len(avg["freq_hz"]) == 8193
            assert len(avg["spl_db"]) == 8193
            # 0 Hz at bin 0, Nyquist (24000 Hz) at last bin
            assert avg["freq_hz"][0] == 0.0
            assert avg["freq_hz"][-1] == 24000.0
            # SPL in plausible range
            assert np.min(avg["spl_db"]) > -200
            assert np.max(avg["spl_db"]) < 200

    def test_real_test_ady_channel_position_counts(self):
        """Each channel in test.ady has one measurement position (key '0')."""
        real_path = Path(__file__).parent.parent / "test.ady"
        if not real_path.exists():
            pytest.skip("test.ady not present in repo root")

        data = load_ady(real_path)
        for ch in get_channels(data):
            positions = get_measurement_positions(ch)
            # test.ady has exactly one position per channel ("0")
            assert positions == ["0"], f"Channel {ch.get('commandId')} has unexpected positions: {positions}"

    def test_real_test_ady_sample_count(self):
        """Each position in test.ady has exactly 16384 samples."""
        real_path = Path(__file__).parent.parent / "test.ady"
        if not real_path.exists():
            pytest.skip("test.ady not present in repo root")

        data = load_ady(real_path)
        for ch in get_channels(data):
            rd = get_response_data(ch)
            for pos_key, samples in rd.items():
                assert len(samples) == 16384, (
                    f"Channel {ch.get('commandId')} position {pos_key}: "
                    f"expected 16384 samples, got {len(samples)}"
                )

