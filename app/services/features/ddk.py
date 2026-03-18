"""
app/services/features/ddk.py
Diadochokinesis (DDK) feature extraction.

Measures articulation rate and regularity from rapid /pa-ta-ka/ repetitions.
Uses energy envelope peak detection — no scipy required (numpy only).

Clinical norms (PT-BR adults):
  - Normal rate: 4.0–7.0 syllables/sec
  - Normal regularity: CV < 20%

References:
  Padovani et al. (2009) — Diadococinesia em adultos e idosos, CoDAS/Brazil.
  CAPE-V Brazilian Portuguese adaptation — Behlau et al.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import parselmouth


@dataclass(frozen=True, slots=True)
class DDKFeatures:
    syllable_rate_hz:  float   # detected syllable peaks per second
    triad_rate_hz:     float   # pa-ta-ka triads per second (rate / 3)
    syllable_count:    int     # total peaks detected
    regularity_cv_pct: float   # CV of inter-peak intervals (%)


def extract(snd: parselmouth.Sound) -> DDKFeatures:
    """
    Extract DDK features from a parselmouth Sound object.
    The Sound should be mono; stereo is handled by averaging channels.
    """
    y  = snd.values[0] if snd.values.shape[0] == 1 else snd.values.mean(axis=0)
    sr = float(snd.sampling_frequency)

    # ── Short-time RMS energy envelope ──────────────────────────────────────
    frame_len = int(sr * 0.020)   # 20 ms frames
    hop_len   = int(sr * 0.005)   # 5 ms hop → smooth enough for syllable detection

    n_frames = (len(y) - frame_len) // hop_len
    if n_frames < 5:
        return DDKFeatures(0.0, 0.0, 0, 100.0)

    energy = np.array([
        np.sqrt(np.mean(y[i * hop_len: i * hop_len + frame_len] ** 2))
        for i in range(n_frames)
    ])

    # ── Smooth with 7-frame moving average (35 ms) ──────────────────────────
    k = 7
    energy_s = np.convolve(energy, np.ones(k) / k, mode="same")

    e_max = energy_s.max()
    if e_max < 1e-7:
        return DDKFeatures(0.0, 0.0, 0, 100.0)
    energy_n = energy_s / e_max

    # ── Peak detection (no scipy) ────────────────────────────────────────────
    # A valid peak must be:
    #   • above threshold (0.25 of normalised energy)
    #   • a local maximum (higher than both neighbours)
    #   • at least 70 ms from the previous accepted peak
    threshold = 0.25
    min_dist  = max(1, int(0.070 / (hop_len / sr)))   # 70 ms → samples

    peaks: list[int] = []
    for i in range(1, len(energy_n) - 1):
        if (
            energy_n[i] > threshold
            and energy_n[i] >= energy_n[i - 1]
            and energy_n[i] > energy_n[i + 1]
            and (not peaks or (i - peaks[-1]) >= min_dist)
        ):
            peaks.append(i)

    # ── Rate & regularity ────────────────────────────────────────────────────
    duration   = snd.duration
    count      = len(peaks)
    rate_hz    = count / duration if duration > 0 else 0.0

    if len(peaks) >= 3:
        intervals  = np.diff(peaks).astype(float) * (hop_len / sr)
        mean_i     = intervals.mean()
        cv         = float(intervals.std() / mean_i * 100) if mean_i > 0 else 100.0
    else:
        cv = 100.0

    return DDKFeatures(
        syllable_rate_hz  = round(rate_hz, 2),
        triad_rate_hz     = round(rate_hz / 3.0, 2),
        syllable_count    = count,
        regularity_cv_pct = round(cv, 1),
    )
