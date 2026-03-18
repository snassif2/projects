"""tests/test_features/test_f0.py"""
import numpy as np
import pytest
from app.services.features.f0 import extract


def test_clean_sine_extracts_f0(sine_440, sr):
    result = extract(sine_440, sr)
    assert result is not None
    # pyin on a pure 440 Hz tone should be close
    assert abs(result.f0_mean_hz - 440) < 20, f"Expected ~440 Hz, got {result.f0_mean_hz}"


def test_male_range_f0(sine_220, sr):
    result = extract(sine_220, sr)
    assert result is not None
    assert result.f0_mean_hz < 165, "220 Hz should be classified as male range"


def test_jitter_is_low_for_clean_signal(sine_440, sr):
    result = extract(sine_440, sr)
    assert result is not None
    assert result.jitter_relative_pct < 1.0, "Pure sine should have near-zero jitter"


def test_voiced_fraction_high_for_sine(sine_440, sr):
    result = extract(sine_440, sr)
    assert result is not None
    assert result.voiced_fraction_pct > 70.0


def test_silence_returns_none(silence, sr):
    result = extract(silence, sr)
    assert result is None, "Silence should return None (unanalysable)"


def test_noisy_voice_still_extracts(noisy_voice, sr):
    """Noisy signal should still produce a result, just with higher jitter."""
    result = extract(noisy_voice, sr)
    assert result is not None
