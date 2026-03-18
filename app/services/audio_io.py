"""
app/services/audio_io.py
Handles everything between "bytes arrive" and "numpy array ready for feature extraction".

Responsibilities:
- MIME type validation against the config allowlist
- File size guard
- Downloading audio from S3 into a safe temp file context
- Loading audio with soundfile, resampling with parselmouth to a fixed sample rate
- Duration guards (min/max) applied AFTER silence trimming
- Clean temp file deletion via context manager — no manual os.unlink

Supported formats: WAV, FLAC, OGG/Vorbis, AIFF (via soundfile/libsndfile).
WebM is NOT supported without ffmpeg; configure the frontend to record in WAV or OGG.
"""
from __future__ import annotations

import contextlib
import logging
import tempfile
from pathlib import Path
from typing import Generator

import boto3
import numpy as np
import parselmouth
import soundfile as sf
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.config import Settings

logger = logging.getLogger(__name__)

# Target sample rate for all downstream feature math.
# Resampling here means every extractor works on a consistent signal.
TARGET_SR = 22_050


class AudioValidationError(HTTPException):
    """400-class error raised during audio validation. Never swallowed as 500."""
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=400, detail=detail)


def validate_mime_type(mime_type: str, settings: Settings) -> None:
    """
    Raises AudioValidationError if the MIME type is not in the allowlist.
    Normalises to lowercase before comparison.
    """
    normalised = mime_type.lower().strip()
    allowed = [m.lower() for m in settings.allowed_mime_types]
    if normalised not in allowed:
        raise AudioValidationError(
            detail=f"Unsupported audio format: '{mime_type}'. "
                   f"Allowed: {', '.join(settings.allowed_mime_types)}"
        )


def validate_file_size(size_bytes: int, settings: Settings) -> None:
    """Raises AudioValidationError if declared file size exceeds the cap."""
    if size_bytes > settings.max_file_size_bytes:
        mb = settings.max_file_size_bytes / 1_048_576
        raise AudioValidationError(
            detail=f"File too large. Maximum allowed size is {mb:.0f} MB."
        )


@contextlib.contextmanager
def s3_audio_as_tempfile(
    bucket: str,
    key: str,
    region: str,
) -> Generator[Path, None, None]:
    """
    Context manager: downloads audio from S3 into a NamedTemporaryFile,
    yields the Path, then deletes the file on exit — even on exceptions.

    Usage:
        with s3_audio_as_tempfile(bucket, key, region) as path:
            y, sr = load_audio(path, settings)
    """
    s3 = boto3.client("s3", region_name=region)

    # Preserve the original extension so soundfile picks the right decoder
    suffix = Path(key).suffix or ".wav"

    tmp: tempfile.NamedTemporaryFile | None = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp_path = Path(tmp.name)

        try:
            s3.download_fileobj(bucket, key, tmp)
        except ClientError as exc:
            logger.error("S3 download failed for key=%s: %s", key, exc)
            raise HTTPException(
                status_code=502,
                detail="Could not retrieve audio file from storage.",
            ) from exc
        finally:
            tmp.close()  # must close before soundfile can open on Windows (no-op on Linux)

        yield tmp_path

    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink()  # type: ignore[possibly-undefined]


def load_audio(
    path: Path,
    settings: Settings,
) -> tuple[np.ndarray, int]:
    """
    Loads audio from *path* using soundfile, resamples to TARGET_SR,
    trims leading/trailing silence, and enforces duration constraints.

    Returns:
        (y, sr) — mono float32 array + sample rate

    Raises:
        AudioValidationError — if duration is outside [min, max]
        HTTPException 422  — if the file cannot be decoded at all
    """
    try:
        y_raw, orig_sr = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception as exc:
        logger.warning("soundfile could not decode file=%s: %s", path.name, exc)
        raise HTTPException(
            status_code=422,
            detail="Audio file could not be decoded. Please try recording again.",
        ) from exc

    # Stereo → mono
    if y_raw.ndim == 2:
        y_raw = y_raw.mean(axis=1)

    # Hard-truncate before resampling to avoid processing excess data
    max_samples_orig = int((settings.max_duration_seconds + 2) * orig_sr)
    y_raw = y_raw[:max_samples_orig]

    # Resample to TARGET_SR via parselmouth (Praat) — no scipy needed
    if orig_sr != TARGET_SR:
        snd_tmp = parselmouth.Sound(y_raw.astype(np.float64), sampling_frequency=float(orig_sr))
        snd_resampled = snd_tmp.resample(TARGET_SR, precision=50)
        y: np.ndarray = snd_resampled.values[0].astype(np.float32)
    else:
        y = y_raw

    sr = TARGET_SR

    # Trim silence from both ends
    y_trimmed = _trim_silence(y, top_db=30)

    duration = len(y_trimmed) / sr

    if duration < settings.min_duration_seconds:
        raise AudioValidationError(
            detail=(
                f"Recording too short ({duration:.1f}s). "
                f"Please record at least {settings.min_duration_seconds} seconds "
                f"of sustained phonation."
            )
        )

    # Hard-cap to max_duration after trimming
    max_samples = int(settings.max_duration_seconds * sr)
    y_final = y_trimmed[:max_samples]

    logger.debug(
        "Audio loaded: duration_trimmed=%.2fs, duration_capped=%.2fs, sr=%d",
        duration,
        len(y_final) / sr,
        sr,
    )
    return y_final, sr


def _trim_silence(
    y: np.ndarray,
    top_db: float = 30.0,
    frame_length: int = 2048,
    hop_length: int = 512,
) -> np.ndarray:
    """
    Remove leading/trailing silence based on per-frame RMS energy.
    Equivalent to librosa.effects.trim with the same default top_db.
    """
    if len(y) < frame_length:
        return y

    n_frames = (len(y) - frame_length) // hop_length + 1
    rms = np.array([
        np.sqrt(np.mean(y[i * hop_length : i * hop_length + frame_length] ** 2))
        for i in range(n_frames)
    ])

    if rms.max() < 1e-10:
        return y

    # Linear threshold relative to peak RMS
    threshold = rms.max() * (10.0 ** (-top_db / 20.0))
    voiced = rms > threshold

    if not voiced.any():
        return y

    start_frame = int(np.argmax(voiced))
    end_frame = int(n_frames - 1 - np.argmax(voiced[::-1]))

    start_sample = start_frame * hop_length
    end_sample = min((end_frame + 1) * hop_length + frame_length, len(y))

    return y[start_sample:end_sample]
