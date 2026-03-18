"""
tests/conftest.py
Shared pytest fixtures.
All audio is synthesised — no real recordings needed in CI.
"""
from __future__ import annotations

import numpy as np
import pytest

SR = 22_050  # must match audio_io.TARGET_SR


@pytest.fixture
def sr() -> int:
    return SR


@pytest.fixture
def sine_440(sr) -> np.ndarray:
    """5-second 440 Hz sine wave — clean, fully voiced. Ideal for HNR/F0 tests."""
    t = np.linspace(0, 5.0, int(5.0 * sr), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


@pytest.fixture
def sine_220(sr) -> np.ndarray:
    """5-second 220 Hz sine — male-range F0."""
    t = np.linspace(0, 5.0, int(5.0 * sr), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


@pytest.fixture
def noisy_voice(sr, sine_440) -> np.ndarray:
    """440 Hz sine + 20% white noise — simulates a rough voice."""
    noise = 0.1 * np.random.default_rng(42).standard_normal(len(sine_440)).astype(np.float32)
    return sine_440 + noise


@pytest.fixture
def silence(sr) -> np.ndarray:
    """3-second silence — should fail duration check after trimming."""
    return np.zeros(int(3.0 * sr), dtype=np.float32)


@pytest.fixture
def short_audio(sr) -> np.ndarray:
    """2-second voiced signal — below minimum duration."""
    t = np.linspace(0, 2.0, int(2.0 * sr), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
