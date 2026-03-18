"""
app/services/features/hnr.py
Harmonics-to-Noise Ratio via Praat's autocorrelation method.

Uses parselmouth (Praat) instead of a manual autocorrelation proxy.
Praat's HNR AC algorithm is the clinical reference implementation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import parselmouth
from parselmouth.praat import call

logger = logging.getLogger(__name__)

F0_MIN_HZ = 75.0


@dataclass(frozen=True, slots=True)
class HNRFeatures:
    hnr_db: float


def extract(y: np.ndarray, sr: int) -> HNRFeatures:
    """
    Compute HNR using Praat's autocorrelation method (harmonicity AC).
    Returns HNRFeatures(hnr_db=0.0) on failure so callers always get a value.
    """
    try:
        snd = parselmouth.Sound(y.astype(np.float64), sampling_frequency=float(sr))

        # time_step=0.01s, min_pitch=F0_MIN_HZ, silence_threshold=0.1, periods_per_window=1.0
        harmonicity = call(
            snd, "To Harmonicity (cc)", 0.01, F0_MIN_HZ, 0.1, 1.0
        )
        hnr_mean = call(harmonicity, "Get mean", 0.0, 0.0)

        if hnr_mean is None or np.isnan(hnr_mean):
            logger.warning("HNR returned NaN — likely unvoiced or silent audio")
            return HNRFeatures(hnr_db=0.0)

        return HNRFeatures(hnr_db=round(float(hnr_mean), 2))

    except Exception as exc:
        logger.warning("HNR extraction failed: %s", exc)
        return HNRFeatures(hnr_db=0.0)
