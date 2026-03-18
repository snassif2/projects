"""
app/services/features/amplitude.py
Shimmer and RMS amplitude statistics.

- Shimmer (local dB) via Praat PointProcess — MDVP-equivalent clinical measure
- RMS mean/std computed directly from the signal with numpy (no library needed)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import parselmouth
from parselmouth.praat import call

logger = logging.getLogger(__name__)

FRAME_LENGTH = 2048
HOP_LENGTH = 512
F0_MIN_HZ = 75.0
F0_MAX_HZ = 500.0


@dataclass(frozen=True, slots=True)
class AmplitudeFeatures:
    shimmer_local_db: float      # Praat local shimmer in dB
    rms_mean: float
    rms_std: float


def extract(y: np.ndarray, sr: int) -> AmplitudeFeatures:  # noqa: ARG001
    """
    sr is accepted for API consistency; RMS stats are sample-rate independent.
    Shimmer uses parselmouth (sr is embedded in the Sound object).
    """
    # RMS stats — pure numpy, no library dependency
    n_frames = max(1, (len(y) - FRAME_LENGTH) // HOP_LENGTH + 1)
    rms_values = np.array([
        np.sqrt(np.mean(y[i * HOP_LENGTH : i * HOP_LENGTH + FRAME_LENGTH] ** 2))
        for i in range(n_frames)
    ])

    rms_mean = float(np.mean(rms_values))
    rms_std = float(np.std(rms_values))

    if rms_mean < 1e-9:
        logger.warning("RMS mean near zero — likely silent audio")
        return AmplitudeFeatures(shimmer_local_db=0.0, rms_mean=0.0, rms_std=0.0)

    shimmer_db = _extract_shimmer(y, sr)

    return AmplitudeFeatures(
        shimmer_local_db=shimmer_db,
        rms_mean=round(rms_mean, 6),
        rms_std=round(rms_std, 6),
    )


def _extract_shimmer(y: np.ndarray, sr: int) -> float:
    """
    Compute Praat local shimmer (dB) via PointProcess.
    Returns 0.0 on failure so callers always receive a numeric value.
    """
    try:
        snd = parselmouth.Sound(y.astype(np.float64), sampling_frequency=float(sr))
        pp = call(snd, "To PointProcess (periodic, cc)", F0_MIN_HZ, F0_MAX_HZ)
        # args: start, end, shortest_period, longest_period, max_period_factor, max_amplitude_factor
        shimmer = call([snd, pp], "Get shimmer (local, dB)", 0.0, 0.0, 0.0001, 0.02, 1.3, 1.6)
        if np.isnan(shimmer):
            return 0.0
        return round(float(shimmer), 4)
    except Exception as exc:
        logger.warning("Shimmer extraction failed: %s", exc)
        return 0.0
