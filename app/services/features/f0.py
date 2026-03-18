"""
app/services/features/f0.py
Fundamental frequency (F0) extraction and jitter.

Uses parselmouth (Praat Python bindings) — the clinical standard for voice analysis.
- F0 via autocorrelation pitch tracking (same algorithm as Praat's default)
- Jitter (local) via PointProcess — MDVP-equivalent, not a proxy

Praat is the industry-standard tool used by speech pathologists worldwide.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import parselmouth
from parselmouth.praat import call

logger = logging.getLogger(__name__)

F0_MIN_HZ = 75.0
F0_MAX_HZ = 500.0


@dataclass(frozen=True, slots=True)
class F0Features:
    f0_mean_hz: float
    f0_std_hz: float
    f0_min_hz: float
    f0_max_hz: float
    jitter_relative_pct: float   # Praat local jitter (%)
    voiced_fraction_pct: float   # % of analysis frames classified as voiced


def extract(y: np.ndarray, sr: int) -> F0Features | None:
    """
    Returns F0Features or None if not enough voiced frames are found.
    Caller should treat None as an unanalysable recording.
    """
    try:
        snd = parselmouth.Sound(y.astype(np.float64), sampling_frequency=float(sr))

        pitch = snd.to_pitch_ac(
            pitch_floor=F0_MIN_HZ,
            pitch_ceiling=F0_MAX_HZ,
        )

        # selected_array['frequency'] is 0.0 for unvoiced frames
        f0_array = pitch.selected_array["frequency"]
        f0_clean = f0_array[f0_array > 0.0]

    except Exception as exc:
        logger.warning("Pitch extraction failed: %s", exc)
        return None

    if len(f0_clean) < 10:
        logger.warning("Too few voiced frames (%d) for reliable F0 analysis", len(f0_clean))
        return None

    voiced_fraction_pct = round(float(len(f0_clean) / max(len(f0_array), 1)) * 100.0, 2)

    # Praat local jitter via PointProcess (period-to-period perturbation)
    jitter_rel_pct = _extract_jitter(snd)

    return F0Features(
        f0_mean_hz=round(float(np.mean(f0_clean)), 2),
        f0_std_hz=round(float(np.std(f0_clean)), 2),
        f0_min_hz=round(float(np.min(f0_clean)), 2),
        f0_max_hz=round(float(np.max(f0_clean)), 2),
        jitter_relative_pct=jitter_rel_pct,
        voiced_fraction_pct=voiced_fraction_pct,
    )


def _extract_jitter(snd: parselmouth.Sound) -> float:
    """
    Compute Praat local jitter (%) via PointProcess.
    Returns 0.0 on failure so callers always receive a numeric value.
    """
    try:
        pp = call(snd, "To PointProcess (periodic, cc)", F0_MIN_HZ, F0_MAX_HZ)
        # args: start, end, shortest_period, longest_period, max_period_factor
        jitter = call(pp, "Get jitter (local)", 0.0, 0.0, 0.0001, 0.02, 1.3)
        if np.isnan(jitter):
            return 0.0
        return round(float(jitter) * 100.0, 4)
    except Exception as exc:
        logger.warning("Jitter extraction failed: %s", exc)
        return 0.0
