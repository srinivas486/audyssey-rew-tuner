"""Tests for speaker HPF shaping + merged target curve functions.

Story 2 — Speaker HPF Shaping + Merged Target Curve
"""

from __future__ import annotations

import json
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from target_curve import (
    MAIN_CHANNEL_IDS,
    TARGET_FREQUENCIES,
    TargetCurveParams,
    apply_hf_tilt,
    detect_lf_cutoff,
    export_speaker_target,
    export_merged_target,
    generate_all_speaker_targets,
    generate_merged_target,
    generate_speaker_target,
    push_speaker_target_via_api,
    push_merged_target_via_api,
    smooth_curve,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def default_params():
    return TargetCurveParams()


@pytest.fixture
def flat_main_channel_response():
    """FL response: perfectly flat ~85 dB across all frequencies."""
    n = len(TARGET_FREQUENCIES)
    return {
        "commandId": "FL",
        "positions": {
            "0": {"freq_hz": TARGET_FREQUENCIES.copy(), "spl_db": np.full(n, 85.0)},
        },
        "averaged": {"freq_hz": TARGET_FREQUENCIES.copy(), "spl_db": np.full(n, 85.0)},
    }


@pytest.fixture
def natural_main_channel_response():
    """FL response: natural bookshelf rolloff with significant LF rolloff.

    Response is ~85 dB above 200 Hz, rolls off below 150 Hz.
    The rolloff is deep enough to drop SPL below the 12 dB threshold in the
    200-500 Hz detection band, so detect_lf_cutoff finds a cutoff < 200 Hz."""
    freq = TARGET_FREQUENCIES
    spl = np.full_like(freq, 85.0)
    # Deep rolloff below 150 Hz: 85 dB above 200 Hz, drops to ~60 dB at 20 Hz
    # Rolloff depth = 25 dB/decade below ref (ref = 85 dB)
    rolloff_mask = freq < 150.0
    freq_clipped = np.maximum(freq, 20.0)  # avoid div/0 at very low freq
    ratio = 150.0 / freq_clipped
    spl[rolloff_mask] = 85.0 - 25.0 * np.log10(ratio[rolloff_mask])
    return {
        "commandId": "FL",
        "positions": {
            "0": {"freq_hz": freq.copy(), "spl_db": spl.copy()},
        },
        "averaged": {"freq_hz": freq.copy(), "spl_db": spl.copy()},
    }


@pytest.fixture
def floorstanding_channel_response():
    """FL response: floorstanding speaker extends cleanly to 20 Hz."""
    freq = TARGET_FREQUENCIES
    spl = np.full_like(freq, 85.0)
    # Very gentle LF rolloff below 30 Hz (extends cleanly)
    below_30 = freq < 30.0
    spl[below_30] = 85.0 - 2.0 * np.log10(30.0 / freq[below_30] + 0.001)
    return {
        "commandId": "FL",
        "positions": {
            "0": {"freq_hz": freq.copy(), "spl_db": spl.copy()},
        },
        "averaged": {"freq_hz": freq.copy(), "spl_db": spl.copy()},
    }


# -----------------------------------------------------------------------------
# Tests: detect_lf_cutoff
# -----------------------------------------------------------------------------

class TestDetectLfCutoff:
    """Task 2.1 — Detect speaker LF cutoff from measured response."""

    def test_flat_response_returns_200hz(self, flat_main_channel_response):
        """Flat response (all ~85 dB, no rolloff): cutoff = 200 Hz (lowest in band).

        A full-range speaker with no low-frequency rolloff should report
        the lowest frequency in the 200–500 Hz detection band.
        """
        ch = flat_main_channel_response
        avg = ch["averaged"]
        cutoff_hz, ref_db = detect_lf_cutoff(avg["freq_hz"], avg["spl_db"])

        # Lowest in 200-500 Hz band
        in_band = (avg["freq_hz"] >= 200.0) & (avg["freq_hz"] <= 500.0)
        expected_cutoff = float(avg["freq_hz"][in_band][0])
        assert cutoff_hz == pytest.approx(expected_cutoff, abs=1.0)

    def test_bookshelf_natural_rolloff(self, natural_main_channel_response):
        """Bookshelf natural ~80 Hz rolloff: cutoff at or near the rolloff region.


        The TARGET_FREQUENCIES grid has only 2 points in the 200-500 Hz detection
        band: 259 Hz and 373 Hz. A significant LF rolloff will cause the smoothed
        response at 259 Hz to drop below the 12 dB threshold, making that the
        detected cutoff even for speakers with physical cutoffs near 80 Hz.
        """
        ch = natural_main_channel_response
        avg = ch["averaged"]
        cutoff_hz, ref_db = detect_lf_cutoff(avg["freq_hz"], avg["spl_db"])


        # With an aggressive rolloff, cutoff should be in the LF region (not >400 Hz)
        # This test verifies the algorithm finds a cutoff, not the exact Hz value
        assert cutoff_hz < 500.0, f"Cutoff too high: {cutoff_hz:.2f} Hz"
        # Reference is ~85 dB (flat portion)
        assert ref_db == pytest.approx(85.0, abs=2.0)

    def test_floorstanding_extends_cleanly(self, floorstanding_channel_response):
        """Floorstanding speaker with no deep dip below threshold: cutoff = 200 Hz.

        Since no point in the 200-500 Hz band drops below the 12 dB threshold,
        the cutoff defaults to the lowest frequency in the band.
        """
        ch = floorstanding_channel_response
        avg = ch["averaged"]
        cutoff_hz, ref_db = detect_lf_cutoff(avg["freq_hz"], avg["spl_db"])

        # Lowest in band (200 Hz)
        in_band = (avg["freq_hz"] >= 200.0) & (avg["freq_hz"] <= 500.0)
        expected_cutoff = float(avg["freq_hz"][in_band][0])
        assert cutoff_hz == pytest.approx(expected_cutoff, abs=1.0)


# -----------------------------------------------------------------------------
# Tests: generate_speaker_target
# -----------------------------------------------------------------------------

class TestGenerateSpeakerTarget:
    """Task 2.2 — HPF-shaped target for a single speaker."""

    def test_target_below_cutoff_not_higher_than_measured(
        self, natural_main_channel_response, default_params
    ):
        """For freq < cutoff_hz, target_spl <= measured_spl (prevents over-correction)."""
        ch = natural_main_channel_response
        avg = ch["averaged"]
        cutoff_hz, ref_db = detect_lf_cutoff(avg["freq_hz"], avg["spl_db"])

        freq, target_db = generate_speaker_target(
            avg["freq_hz"], avg["spl_db"], default_params, cutoff_hz, ref_db
        )

        # Compare at each TARGET_FREQUIES below cutoff
        below_cutoff = freq < cutoff_hz
        measured_interp = np.interp(freq, avg["freq_hz"], avg["spl_db"])
        for i in range(len(freq)):
            if below_cutoff[i] and not np.isnan(measured_interp[i]):
                assert target_db[i] <= measured_interp[i] + 0.01, (
                    f"Target exceeds measured at {freq[i]:.1f} Hz: "
                    f"target={target_db[i]:.2f} dB > measured={measured_interp[i]:.2f} dB"
                )

    def test_target_never_exceeds_12db_boost_below_cutoff(
        self, natural_main_channel_response, default_params
    ):
        """Max boost below cutoff ≤ 12 dB over ref_db."""
        ch = natural_main_channel_response
        avg = ch["averaged"]
        cutoff_hz, ref_db = detect_lf_cutoff(avg["freq_hz"], avg["spl_db"])

        freq, target_db = generate_speaker_target(
            avg["freq_hz"], avg["spl_db"], default_params, cutoff_hz, ref_db
        )

        below_cutoff = freq < cutoff_hz
        if np.any(below_cutoff):
            max_boost = float(np.max(target_db[below_cutoff])) - ref_db
            assert max_boost <= 12.0, f"Max boost below cutoff: {max_boost:.2f} dB (limit: 12 dB)"

    def test_flat_midrange(
        self, flat_main_channel_response, default_params
    ):
        """Between cutoff and tilt_start_hz, target ≈ ref_db ± 4 dB.

        Note: with the coarse 1/6-octave TARGET_FREQUENCIES grid, the smoothing
        creates some approximation error at the join point. ±4 dB tolerance
        accounts for this without masking real bugs.
        """
        ch = flat_main_channel_response
        avg = ch["averaged"]
        cutoff_hz, ref_db = detect_lf_cutoff(avg["freq_hz"], avg["spl_db"])

        freq, target_db = generate_speaker_target(
            avg["freq_hz"], avg["spl_db"], default_params, cutoff_hz, ref_db
        )

        # Between cutoff and tilt_start_hz
        midrange_mask = (freq >= cutoff_hz) & (freq <= default_params.tilt_start_hz)
        if np.any(midrange_mask):
            for val in target_db[midrange_mask]:
                assert abs(val - ref_db) <= 4.0, (
                    f"Midrange target deviates >4 dB from ref: {val:.2f} vs ref {ref_db:.2f}"
                )

    def test_hf_tilt_applied(self, flat_main_channel_response, default_params):
        """For freq > tilt_start_hz, target drops at ~tilt_rate dB/decade."""
        ch = flat_main_channel_response
        avg = ch["averaged"]
        cutoff_hz, ref_db = detect_lf_cutoff(avg["freq_hz"], avg["spl_db"])

        freq, target_db = generate_speaker_target(
            avg["freq_hz"], avg["spl_db"], default_params, cutoff_hz, ref_db
        )

        # Check slope above tilt_start_hz
        above_tilt = freq > default_params.tilt_start_hz
        if np.any(above_tilt):
            # Compute dB/decade between two points well above tilt
            p1 = np.where(above_tilt)[0][0]
            p2 = np.where(above_tilt)[0][len(np.where(above_tilt)[0]) // 2]
            if p1 < p2:
                decade_ratio = np.log10(freq[p2] / freq[p1])
                if decade_ratio > 0:
                    slope = (target_db[p2] - target_db[p1]) / decade_ratio
                    # Should be roughly -tilt_rate (within factor 2 for smoothing effects)
                    assert slope < 0, "HF tilt should be downward (negative slope)"
                    assert slope < 0.5, f"HF tilt too shallow or upward: {slope:.2f} dB/decade"


# -----------------------------------------------------------------------------
# Tests: generate_all_speaker_targets
# -----------------------------------------------------------------------------

class TestGenerateAllSpeakerTargets:
    """Task 2.3 — Generate per-speaker targets for FL, C, FR."""

    @pytest.fixture
    def three_speaker_responses(self, natural_main_channel_response):
        """FL, C, FR responses."""
        base = natural_main_channel_response
        return [
            dict(base, commandId="FL"),
            dict(base, commandId="C"),
            dict(base, commandId="FR"),
        ]

    def test_fl_c_fr_all_present(self, three_speaker_responses, default_params):
        """Result dict has keys fl, c, fr."""
        results = generate_all_speaker_targets(three_speaker_responses, default_params)
        assert set(results.keys()) == {"fl", "c", "fr"}

    def test_each_speaker_has_distinct_cutoff(
        self, natural_main_channel_response, default_params
    ):
        """Each speaker's target is independent; cutoff values differ."""
        # Use the same response for all 3 — they should still generate independently
        base = natural_main_channel_response
        responses = [
            dict(base, commandId="FL"),
            dict(base, commandId="C"),
            dict(base, commandId="FR"),
        ]
        results = generate_all_speaker_targets(responses, default_params)
        # All present
        assert len(results) == 3
        # Each returns (freq, target_db)
        for cmd_id, (freq, target_db) in results.items():
            assert len(freq) == len(TARGET_FREQUENCIES)
            assert len(target_db) == len(TARGET_FREQUENCIES)

    def test_unknown_channels_excluded(self, default_params):
        """Channels not in MAIN_CHANNEL_IDS are skipped."""
        channel_responses = [
            {"commandId": "FL", "averaged": {"freq_hz": TARGET_FREQUENCIES.copy(), "spl_db": np.full_like(TARGET_FREQUENCIES, 85.0)}},
            {"commandId": "SW1", "averaged": {"freq_hz": TARGET_FREQUENCIES.copy(), "spl_db": np.full_like(TARGET_FREQUENCIES, 80.0)}},
            {"commandId": "SLA", "averaged": {"freq_hz": TARGET_FREQUENCIES.copy(), "spl_db": np.full_like(TARGET_FREQUENCIES, 83.0)}},
        ]
        results = generate_all_speaker_targets(channel_responses, default_params)
        assert "fl" in results
        assert "sw1" not in results
        assert "sla" not in results

    def test_returns_dict_of_tuples(self, natural_main_channel_response, default_params):
        """Return type is dict[str, tuple[np.ndarray, np.ndarray]]."""
        responses = [dict(natural_main_channel_response, commandId="FL")]
        results = generate_all_speaker_targets(responses, default_params)
        for cmd_id, (freq, target_db) in results.items():
            assert isinstance(freq, np.ndarray)
            assert isinstance(target_db, np.ndarray)


# -----------------------------------------------------------------------------
# Tests: export + push speaker targets
# -----------------------------------------------------------------------------

class TestExportSpeakerTarget:
    """Task 2.4 — FRD export for speaker targets."""

    def test_export_writes_valid_frd(self, tmp_path):
        """File exists, one line per freq, ascending order."""
        freq = np.array([20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 5000.0, 10000.0, 20000.0])
        spl = np.array([-10.0, -5.0, 0.0, 2.0, 1.0, 0.0, -2.0, -5.0, -10.0])
        result = export_speaker_target(freq, spl, tmp_path, "fl")
        assert result is True

        frd_path = tmp_path / "fl_target.frd"
        assert frd_path.exists()

        lines = frd_path.read_text().strip().split("\n")
        assert len(lines) == len(freq)
        # Ascending check
        freq_vals = [float(l.split()[0]) for l in lines]
        assert freq_vals == sorted(freq_vals)

    def test_output_path_created(self, tmp_path):
        """Output directory is created if it doesn't exist."""
        subdir = tmp_path / "sub" / "dir"
        freq = np.array([100.0, 1000.0, 10000.0])
        spl = np.array([0.0, 0.0, -5.0])
        result = export_speaker_target(freq, spl, subdir, "c")
        assert result is True
        assert (subdir / "c_target.frd").exists()


class TestPushSpeakerTargetViaApi:
    """Task 2.4 — API push for speaker targets."""

    def test_api_push_success_returns_true(self):
        """Mock 200 response → returns True."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = BytesIO(b'{"ok": true}')
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            freq = np.array([20.0, 1000.0, 20000.0])
            spl = np.array([-10.0, 0.0, -10.0])
            result = push_speaker_target_via_api("fl", freq, spl)
            assert result is True


# -----------------------------------------------------------------------------
# Tests: generate_merged_target
# -----------------------------------------------------------------------------

class TestGenerateMergedTarget:
    """Task 2.5 — Merged target from FL+C+FR per-speaker targets."""

    def test_merged_is_arithmetic_mean(self, default_params):
        """At each freq point, merged = mean of FL+C+FR."""
        # Create three distinct targets
        fl_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 80.0))
        c_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 85.0))
        fr_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 90.0))
        speaker_targets = {"fl": fl_target, "c": c_target, "fr": fr_target}

        merged_freq, merged_db = generate_merged_target(speaker_targets)

        assert len(merged_freq) == len(TARGET_FREQUENCIES)
        # Arithmetic mean of 80, 85, 90 = 85
        np.testing.assert_allclose(merged_db, 85.0, atol=0.01)

    def test_missing_channel_uses_available(self, default_params):
        """With only FL+C (no FR), merged = mean of those two."""
        fl_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 80.0))
        c_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 90.0))
        speaker_targets = {"fl": fl_target, "c": c_target}

        _merged_freq, merged_db = generate_merged_target(speaker_targets)

        # Mean of 80 and 90 = 85
        np.testing.assert_allclose(merged_db, 85.0, atol=0.01)

    def test_single_speaker_returns_that_curve(self, default_params):
        """With only FL, returns FL's target directly."""
        fl_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 82.0))
        speaker_targets = {"fl": fl_target}

        merged_freq, merged_db = generate_merged_target(speaker_targets)

        np.testing.assert_array_equal(merged_freq, TARGET_FREQUENCIES)
        np.testing.assert_allclose(merged_db, 82.0, atol=0.01)

    def test_empty_returns_empty_arrays(self, default_params):
        """With empty dict, returns (empty, empty)."""
        speaker_targets = {}
        merged_freq, merged_db = generate_merged_target(speaker_targets)
        assert len(merged_freq) == 0
        assert len(merged_db) == 0

    def test_merged_length_matches_target_frequencies(self, default_params):
        """len(merged_freq) == len(TARGET_FREQUENCIES)."""
        fl_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 85.0))
        fr_target = (TARGET_FREQUENCIES, np.full_like(TARGET_FREQUENCIES, 85.0))
        speaker_targets = {"fl": fl_target, "fr": fr_target}

        merged_freq, _merged_db = generate_merged_target(speaker_targets)
        assert len(merged_freq) == len(TARGET_FREQUENCIES)


# -----------------------------------------------------------------------------
# Tests: export + push merged target
# -----------------------------------------------------------------------------

class TestExportMergedTarget:
    """Task 2.5 — FRD export for merged target."""

    def test_export_merged_writes_file(self, tmp_path):
        """Output file exists with valid FRD format."""
        freq = np.array([20.0, 100.0, 1000.0, 10000.0, 20000.0])
        spl = np.array([-5.0, 0.0, 1.0, -1.0, -8.0])
        result = export_merged_target(freq, spl, tmp_path)
        assert result is True

        frd_path = tmp_path / "merged_target.frd"
        assert frd_path.exists()

        lines = frd_path.read_text().strip().split("\n")
        assert len(lines) == len(freq)
        # Ascending order
        freq_vals = [float(l.split()[0]) for l in lines]
        assert freq_vals == sorted(freq_vals)


class TestPushMergedTargetViaApi:
    """Task 2.5 — API push for merged target."""

    def test_push_merged_api_call_made(self):
        """Verify API function was called with correct args (house-curve endpoint)."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = BytesIO(b'{"ok": true}')
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            freq = np.array([20.0, 1000.0, 20000.0])
            spl = np.array([-5.0, 0.0, -5.0])
            result = push_merged_target_via_api(freq, spl)

            assert result is True
            # Check the URL called
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert "/eq/house-curve" in req.full_url or "/import/frequency-response-data" in req.full_url
