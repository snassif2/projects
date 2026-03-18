"""
app/services/features/__init__.py
Orchestrates all feature extractors → FeatureBundle.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import amplitude, f0, hnr, spectral


@dataclass(frozen=True, slots=True)
class FeatureBundle:
    """All extracted features for one audio sample."""
    duration_seconds: float
    f0: f0.F0Features | None
    amplitude: amplitude.AmplitudeFeatures
    spectral: spectral.SpectralFeatures
    hnr: hnr.HNRFeatures


def extract_all(y: np.ndarray, sr: int) -> FeatureBundle:
    """
    Run all feature extractors on the audio signal.
    Returns a complete FeatureBundle.
    f0 may be None if the audio is unanalysable.
    """
    duration = len(y) / sr

    return FeatureBundle(
        duration_seconds=round(duration, 2),
        f0=f0.extract(y, sr),
        amplitude=amplitude.extract(y, sr),
        spectral=spectral.extract(y, sr),
        hnr=hnr.extract(y, sr),
    )
