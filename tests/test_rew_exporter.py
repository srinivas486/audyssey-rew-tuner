"""Tests for rew_exporter module."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from rew_exporter import (
    export_channel_frd,
    push_frequency_response_via_api,
    push_impulse_response_via_api,
    REW_API_DEFAULT_HOST,
    REW_API_DEFAULT_PORT,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def temp_output_dir(tmp_path):
    """Return a temporary directory path for .frd output."""
    d = tmp_path / "frd_output"
    d.mkdir()
    return d


@pytest.fixture
def simple_freq_hz():
    """A simple ascending frequency list: 20 Hz → 200 Hz in 10 Hz steps."""
    return [20.0, 30.0, 40.0, 50.0, 100.0, 200.0]


@pytest.fixture
def simple_spl_db():
    """Corresponding SPL values matching simple_freq_hz."""
    return [-30.0, -28.0, -26.0, -24.0, -20.0, -15.0]


@pytest.fixture
def simple_ir_samples():
    """A simple impulse response: 16384 samples of decaying exponential."""
    n = 16384
    t = np.arange(n) / 48000.0
    return np.exp(-40.0 * t).tolist()


# -----------------------------------------------------------------------------
# export_channel_frd tests
# -----------------------------------------------------------------------------

class TestExportChannelFrd:
    def test_writes_one_line_per_frequency(self, temp_output_dir, simple_freq_hz, simple_spl_db):
        """Output file has exactly one line per frequency bin."""
        ok = export_channel_frd(simple_freq_hz, simple_spl_db, temp_output_dir, "FL")
        assert ok is True

        file_path = temp_output_dir / "FL.frd"
        assert file_path.exists()

        lines = file_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == len(simple_freq_hz)

    def test_lines_are_freq_spl_pairs(self, temp_output_dir, simple_freq_hz, simple_spl_db):
        """Each line is 'freq spl' (space-separated)."""
        ok = export_channel_frd(simple_freq_hz, simple_spl_db, temp_output_dir, "C")
        assert ok is True

        file_path = temp_output_dir / "C.frd"
        for line in file_path.read_text(encoding="utf-8").strip().split("\n"):
            parts = line.split()
            assert len(parts) == 2
            freq, spl = float(parts[0]), float(parts[1])
            assert freq > 0
            assert np.isfinite(spl)

    def test_frequencies_are_ascending_in_file(self, temp_output_dir):
        """Frequencies in the output file are in ascending order."""
        freq_hz = [200.0, 20.0, 100.0, 50.0]
        spl_db = [-15.0, -30.0, -20.0, -24.0]

        ok = export_channel_frd(freq_hz, spl_db, temp_output_dir, "FR")
        assert ok is True

        file_path = temp_output_dir / "FR.frd"
        freqs = [float(line.split()[0]) for line in file_path.read_text(encoding="utf-8").strip().split("\n")]
        assert freqs == sorted(freqs)

    def test_output_file_named_after_channel(self, temp_output_dir, simple_freq_hz, simple_spl_db):
        """Output file is named {channel_name}.frd."""
        ok = export_channel_frd(simple_freq_hz, simple_spl_db, temp_output_dir, "SW1")
        assert ok is True
        assert (temp_output_dir / "SW1.frd").exists()

    def test_accepts_numpy_arrays(self, temp_output_dir):
        """numpy arrays are accepted and converted correctly."""
        freq_hz = np.array([100.0, 1000.0, 10000.0])
        spl_db = np.array([-20.0, -15.0, -25.0])

        ok = export_channel_frd(freq_hz, spl_db, temp_output_dir, "FL")
        assert ok is True

        file_path = temp_output_dir / "FL.frd"
        lines = file_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_accepts_mixed_array_types(self, temp_output_dir):
        """Mix of numpy array and list is accepted."""
        freq_hz = np.array([100.0, 1000.0, 10000.0])
        spl_db = [-20.0, -15.0, -25.0]

        ok = export_channel_frd(freq_hz, spl_db, temp_output_dir, "C")
        assert ok is True
        assert (temp_output_dir / "C.frd").exists()

    def test_returns_false_on_length_mismatch(self, temp_output_dir):
        """Returns False when freq_hz and spl_db have different lengths."""
        freq_hz = [20.0, 30.0, 40.0]
        spl_db = [-30.0, -28.0]  # one short

        ok = export_channel_frd(freq_hz, spl_db, temp_output_dir, "FL")
        assert ok is False
        assert not (temp_output_dir / "FL.frd").exists()

    def test_returns_false_on_empty_data(self, temp_output_dir):
        """Returns False when given empty arrays."""
        ok = export_channel_frd([], [], temp_output_dir, "FL")
        assert ok is False
        assert not (temp_output_dir / "FL.frd").exists()

    def test_creates_output_directory_if_missing(self, tmp_path):
        """Output directory is created if it does not exist."""
        output_dir = tmp_path / "does_not_exist" / "nested"
        ok = export_channel_frd([100.0], [-20.0], output_dir, "FL")
        assert ok is True
        assert (output_dir / "FL.frd").exists()

    def test_creates_string_path_output_dir(self, tmp_path):
        """String path is accepted for output_dir."""
        output_dir = str(tmp_path / "string_output")
        ok = export_channel_frd([100.0], [-20.0], output_dir, "FL")
        assert ok is True
        assert (Path(output_dir) / "FL.frd").exists()

    def test_overwrites_existing_file(self, temp_output_dir, simple_freq_hz, simple_spl_db):
        """Writing twice to the same channel overwrites the file (no error)."""
        ok1 = export_channel_frd(simple_freq_hz, simple_spl_db, temp_output_dir, "FL")
        ok2 = export_channel_frd(simple_freq_hz, simple_spl_db, temp_output_dir, "FL")
        assert ok1 is True
        assert ok2 is True
        assert (temp_output_dir / "FL.frd").exists()


# -----------------------------------------------------------------------------
# push_frequency_response_via_api tests
# -----------------------------------------------------------------------------

class TestPushFrequencyResponseViaApi:
    def test_returns_true_on_successful_post(self, simple_freq_hz, simple_spl_db):
        """Returns True when REW API responds with 2xx."""
        import urllib.error

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            ok = push_frequency_response_via_api(simple_freq_hz, simple_spl_db, "FL")
            assert ok is True
            mock_open.assert_called_once()
            call_args = mock_open.call_args
            req = call_args[0][0]
            assert req.method == "POST"
            body = json.loads(req.data.decode("utf-8"))
            assert body["identifier"] == "FL"

    def test_json_payload_has_correct_structure(self, simple_freq_hz, simple_spl_db):
        """JSON body contains the REW-compatible FrequencyResponseData structure."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            push_frequency_response_via_api(simple_freq_hz, simple_spl_db, "FL")
            req = mock_open.call_args[0][0]
            body = json.loads(req.data.decode("utf-8"))
            assert "identifier" in body
            assert "magnitude" in body
            assert "startFreq" in body
            assert "freqStep" in body
            assert body["identifier"] == "FL"
            assert body["startFreq"] == 20.0
            assert body["freqStep"] == 10.0
            import base64, struct
            decoded = base64.b64decode(body["magnitude"])
            values = struct.unpack(f'>{len(simple_spl_db)}f', decoded)
            assert list(values) == simple_spl_db

    def test_returns_false_on_connection_refused(self, simple_freq_hz, simple_spl_db):
        """Returns False (no crash) when connection is refused."""
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(
            ConnectionRefusedError("Connection refused")
        )):
            ok = push_frequency_response_via_api(simple_freq_hz, simple_spl_db, "FL")
            assert ok is False

    def test_returns_false_on_http_error(self, simple_freq_hz, simple_spl_db):
        """Returns False (no crash) when REW returns an HTTP error code."""
        import urllib.error

        err = urllib.error.HTTPError(
            "http://localhost:4735/",
            500,
            "Internal Server Error",
            {},
            None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            ok = push_frequency_response_via_api(simple_freq_hz, simple_spl_db, "FL")
            assert ok is False

    def test_returns_false_on_os_error(self, simple_freq_hz, simple_spl_db):
        """Returns False (no crash) on socket/DNS errors."""
        with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
            ok = push_frequency_response_via_api(simple_freq_hz, simple_spl_db, "FL")
            assert ok is False

    def test_uses_custom_host_and_port(self, simple_freq_hz, simple_spl_db):
        """Custom host and port are used in the request URL."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            push_frequency_response_via_api(
                simple_freq_hz, simple_spl_db, "FL",
                host="192.168.1.100",
                port=5000,
            )
            req = mock_open.call_args[0][0]
            assert "192.168.1.100" in req.full_url
            assert ":5000" in req.full_url

    def test_returns_false_on_length_mismatch(self, simple_freq_hz, simple_spl_db):
        """Returns False when freq_hz and spl_db lengths differ."""
        ok = push_frequency_response_via_api(
            [20.0, 30.0, 40.0],
            [-30.0, -28.0],  # one short
            "FL",
        )
        assert ok is False

    def test_accepts_numpy_arrays(self):
        """numpy arrays are accepted (converted to lists internally)."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        freq_hz = np.array([100.0, 1000.0, 10000.0])
        spl_db = np.array([-20.0, -15.0, -25.0])

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ok = push_frequency_response_via_api(freq_hz, spl_db, "FL")
            assert ok is True

    def test_default_host_and_port(self):
        """Default host/port constants are correct."""
        assert REW_API_DEFAULT_HOST == "localhost"
        assert REW_API_DEFAULT_PORT == 4735


# -----------------------------------------------------------------------------
# push_impulse_response_via_api tests
# -----------------------------------------------------------------------------

class TestPushImpulseResponseViaApi:
    def test_returns_true_on_successful_post(self, simple_ir_samples):
        """Returns True when REW API responds with 2xx."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            ok = push_impulse_response_via_api(simple_ir_samples, "FL")
            assert ok is True
            mock_open.assert_called_once()
            req = mock_open.call_args[0][0]
            assert req.method == "POST"
            body = json.loads(req.data.decode("utf-8"))
            assert body["identifier"] == "FL"

    def test_json_payload_has_correct_structure(self, simple_ir_samples):
        """JSON body contains the REW-compatible ImpulseResponseData fields."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            push_impulse_response_via_api(simple_ir_samples, "FL", sample_rate=48000.0)
            req = mock_open.call_args[0][0]
            body = json.loads(req.data.decode("utf-8"))

            # Root-level fields per REW swagger
            assert body["identifier"] == "FL"
            assert body["startTime"] == 0.0
            assert body["sampleRate"] == 48000.0
            assert body["splOffset"] == 0.0
            assert body["applyCal"] is False
            assert "data" in body

            # data must be valid base64 big-endian float32
            import base64, struct
            decoded = base64.b64decode(body["data"])
            n_expected = len(simple_ir_samples)
            values = struct.unpack(f'>{n_expected}f', decoded)
            np.testing.assert_array_almost_equal(values, simple_ir_samples)

    def test_uses_correct_endpoint(self, simple_ir_samples):
        """Request is POSTed to /import/impulse-response-data."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            push_impulse_response_via_api(simple_ir_samples, "FL")
            req = mock_open.call_args[0][0]
            assert "/import/impulse-response-data" in req.full_url

    def test_uses_custom_host_and_port(self, simple_ir_samples):
        """Custom host and port are used in the request URL."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            push_impulse_response_via_api(
                simple_ir_samples, "FL",
                host="192.168.1.100",
                port=5000,
            )
            req = mock_open.call_args[0][0]
            assert "192.168.1.100" in req.full_url
            assert ":5000" in req.full_url

    def test_returns_false_on_connection_refused(self, simple_ir_samples):
        """Returns False (no crash) when connection is refused."""
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(
            ConnectionRefusedError("Connection refused")
        )):
            ok = push_impulse_response_via_api(simple_ir_samples, "FL")
            assert ok is False

    def test_returns_false_on_http_error(self, simple_ir_samples):
        """Returns False (no crash) when REW returns an HTTP error code."""
        import urllib.error

        err = urllib.error.HTTPError(
            "http://localhost:4735/",
            500,
            "Internal Server Error",
            {},
            None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            ok = push_impulse_response_via_api(simple_ir_samples, "FL")
            assert ok is False

    def test_returns_false_on_os_error(self, simple_ir_samples):
        """Returns False (no crash) on socket/DNS errors."""
        with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
            ok = push_impulse_response_via_api(simple_ir_samples, "FL")
            assert ok is False

    def test_returns_false_on_empty_data(self):
        """Returns False when given empty sample list."""
        ok = push_impulse_response_via_api([], "FL")
        assert ok is False

    def test_accepts_numpy_array(self):
        """numpy array is accepted and converted correctly."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        samples = np.exp(-40.0 * np.arange(16384) / 48000.0)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ok = push_impulse_response_via_api(samples, "FL")
            assert ok is True

    def test_default_sample_rate_is_48000(self, simple_ir_samples):
        """Default sample rate in payload is 48000.0 Hz."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            push_impulse_response_via_api(simple_ir_samples, "FL")
            req = mock_open.call_args[0][0]
            body = json.loads(req.data.decode("utf-8"))
            assert body["sampleRate"] == 48000.0


# -----------------------------------------------------------------------------
# Integration: export + push together
# -----------------------------------------------------------------------------

class TestExportAndPushIntegration:
    def test_export_and_push_work_together(self, temp_output_dir, simple_freq_hz, simple_spl_db):
        """export_channel_frd and push_frequency_response_via_api can be used in a loop."""
        channels = ["FL", "C", "FR"]
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            for ch in channels:
                freq = list(simple_freq_hz)
                spl = list(simple_spl_db)

                ok_frd = export_channel_frd(freq, spl, temp_output_dir, ch)
                assert ok_frd is True
                assert (temp_output_dir / f"{ch}.frd").exists()

                ok_api = push_frequency_response_via_api(freq, spl, ch)
                assert ok_api is True

    def test_export_and_push_work_on_real_test_ady(self):
        """Full pipeline on the real test.ady file (if present)."""
        real_path = Path(__file__).parent.parent / "test.ady"
        if not real_path.exists():
            pytest.skip("test.ady not present in repo root")

        from ady_parser import load_ady, get_all_channels_freq_response

        data = load_ady(real_path)
        channel_responses = get_all_channels_freq_response(data)

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_resp):
                for ch in channel_responses:
                    cmd_id = ch["commandId"]
                    avg = ch["averaged"]
                    freq = list(avg["freq_hz"])
                    spl = list(avg["spl_db"])

                    ok_frd = export_channel_frd(freq, spl, tmpdir, cmd_id)
                    assert ok_frd is True, f".frd export failed for {cmd_id}"
                    assert (Path(tmpdir) / f"{cmd_id}.frd").exists()

                    ok_api = push_frequency_response_via_api(freq, spl, cmd_id)
                    assert ok_api is True, f"REW API push failed for {cmd_id}"

    def test_ir_push_on_real_test_ady(self):
        """Full IR pipeline on the real test.ady file (if present)."""
        real_path = Path(__file__).parent.parent / "test.ady"
        if not real_path.exists():
            pytest.skip("test.ady not present in repo root")

        from ady_parser import load_ady, get_all_channels_ir

        data = load_ady(real_path)
        channel_irs = get_all_channels_ir(data)

        # 11 channels
        assert len(channel_irs) == 11

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            for ch_ir in channel_irs:
                ok = push_impulse_response_via_api(
                    ch_ir["samples"],
                    ch_ir["commandId"],
                    sample_rate=ch_ir["sample_rate"],
                )
                assert ok is True, f"IR push failed for {ch_ir['commandId']}"
                # Verify all 16384 samples were sent
                req = mock_open.call_args[0][0]
                body = json.loads(req.data.decode("utf-8"))
                assert body["identifier"] == ch_ir["commandId"]
                assert body["sampleRate"] == 48000.0
                import base64, struct
                decoded = struct.unpack(
                    f'>{ch_ir["n_samples"]}f',
                    base64.b64decode(body["data"])
                )
                assert len(decoded) == ch_ir["n_samples"] == 16384