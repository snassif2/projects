"""
app/services/features/spectral.py
Spectral centroid, rolloff, bandwidth, and formant estimation.

- Spectral statistics (centroid, rolloff, bandwidth) via numpy FFT — no librosa needed
- Formant estimation via Praat Burg method (parselmouth) — far more accurate than LPC peak-picking
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import parselmouth
from parselmouth.praat import call

logger = logging.getLogger(__name__)

N_FFT = 2048
HOP_LENGTH = 512
MAX_FORMANTS = 4


@dataclass(frozen=True, slots=True)
class SpectralFeatures:
    centroid_hz: float
    rolloff_hz: float
    bandwidth_hz: float
    formant_peaks_hz: list[float] = field(default_factory=list)


def extract(y: np.ndarray, sr: int) -> SpectralFeatures:
    centroid, rolloff, bandwidth = _spectral_stats(y, sr, N_FFT, HOP_LENGTH)
    formant_peaks = _extract_formants(y, sr)

    return SpectralFeatures(
        centroid_hz=centroid,
        rolloff_hz=rolloff,
        bandwidth_hz=bandwidth,
        formant_peaks_hz=formant_peaks,
    )


def _spectral_stats(
    y: np.ndarray, sr: int, n_fft: int, hop_length: int
) -> tuple[float, float, float]:
    """
    Compute mean spectral centroid, rolloff (85%), and bandwidth using numpy FFT.
    Frame-by-frame with Hann window — equivalent to librosa's spectral features.
    """
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))

    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    n_frames = (len(y) - n_fft) // hop_length + 1
    centroids: list[float] = []
    rolloffs: list[float] = []
    bandwidths: list[float] = []

    for i in range(n_frames):
        frame = y[i * hop_length : i * hop_length + n_fft] * window
        S = np.abs(np.fft.rfft(frame))
        S_sq = S ** 2
        total = S_sq.sum() + 1e-10

        # Centroid
        c = float((freqs * S_sq).sum() / total)
        centroids.append(c)

        # Rolloff (first frequency where cumulative energy >= 85%)
        cumsum = np.cumsum(S_sq)
        idx = int(np.searchsorted(cumsum, 0.85 * cumsum[-1]))
        rolloffs.append(float(freqs[min(idx, len(freqs) - 1)]))

        # Bandwidth
        bandwidths.append(float(np.sqrt(((freqs - c) ** 2 * S_sq).sum() / total)))

    return (
        round(float(np.mean(centroids)), 2),
        round(float(np.mean(rolloffs)), 2),
        round(float(np.mean(bandwidths)), 2),
    )


def _extract_formants(y: np.ndarray, sr: int) -> list[float]:
    """
    Formant estimation via Praat's Burg algorithm (parselmouth).
    Returns up to MAX_FORMANTS formant frequencies (Hz), sorted ascending.
    Returns empty list on any failure — callers must handle this gracefully.

    Praat's formant tracker is far more robust than LPC peak-picking:
    uses a proper all-pole model with iterative Burg LPC, evaluated at the midpoint
    of the recording for stable vowel-quality estimation.
    """
    try:
        snd = parselmouth.Sound(y.astype(np.float64), sampling_frequency=float(sr))

        # max_number_of_formants=5, maximum_formant=5500 Hz (standard for adult voice)
        formants = call(snd, "To Formant (burg)", 0.0, 5.0, 5500.0, 0.025, 50.0)

        t_mid = snd.duration / 2.0
        peaks: list[float] = []
        for formant_num in range(1, MAX_FORMANTS + 1):
            val = call(formants, "Get value at time", formant_num, t_mid, "Hertz", "Linear")
            if val is not None and not np.isnan(val) and val > 0:
                peaks.append(round(float(val), 1))

        return sorted(peaks)

    except Exception as exc:
        logger.warning("Formant extraction failed: %s", exc)
        return []
