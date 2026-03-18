"""
app/config.py
All runtime configuration via environment variables.
Nothing clinical, infra, or behavioural is hardcoded anywhere else.
"""
from __future__ import annotations
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOZLAB_",
        env_file=".env",
        extra="ignore",
    )

    # ── AWS ───────────────────────────────────────────────────────────────────
    aws_region: str = "us-east-1"
    s3_bucket: str = "vozlab-audio-intake"
    dynamodb_table: str = "vozlab-results"

    # How long the browser has to PUT the file after receiving the presigned URL
    presigned_url_expiry: int = 300          # 5 min

    # DynamoDB item TTL (seconds from creation)
    result_ttl_seconds: int = 86_400         # 24 h — matches S3 lifecycle

    # ── Audio constraints (shared with frontend via GET /config) ─────────────
    max_duration_seconds: int = 15           # 15 s is the clinical MPT norm ceiling
    min_duration_seconds: int = 4            # enforced after silence trimming
    max_file_size_bytes: int = 15_728_640    # 15 MB — covers 30s OGG/WAV

    # ── MPT (Maximum Phonation Time) norms ───────────────────────────────────
    mpt_normal_min_seconds: float = 15.0     # ≥15s → normal
    mpt_borderline_min_seconds: float = 10.0 # 10–14s → borderline; <10s → low

    # MIME types the browser may negotiate and upload.
    # soundfile (libsndfile) supports OGG/Vorbis, WAV, FLAC, AIFF on Lambda Linux.
    # WebM is NOT supported without ffmpeg — configure the frontend to record in OGG or WAV.
    allowed_mime_types: list[str] = [
        "audio/ogg",
        "audio/ogg;codecs=opus",
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
    ]

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Production override: VOZLAB_CORS_ORIGINS='["https://yourdomain.com"]'
    cors_origins: list[str] = ["*"]

    # ── Clinical norms (externalized — never buried in feature code) ─────────
    f0_male_mean_hz: float = 120.0
    f0_male_std_hz: float = 20.0
    f0_male_range_min: float = 80.0
    f0_male_range_max: float = 200.0

    f0_female_mean_hz: float = 200.0
    f0_female_std_hz: float = 35.0
    f0_female_range_min: float = 150.0
    f0_female_range_max: float = 300.0

    # F0 cut-off for gender heuristic (triage only, not clinical ground truth)
    gender_f0_threshold_hz: float = 165.0

    jitter_normal_max_pct: float = 0.6
    shimmer_normal_max_db: float = 0.35   # Praat local shimmer dB norm (MDVP: <0.35 dB)
    hnr_normal_min_db: float = 18.0

    # Health score weights — must sum to 1.0
    score_weight_jitter: float = 0.30
    score_weight_shimmer: float = 0.30
    score_weight_hnr: float = 0.25
    score_weight_voiced: float = 0.15

    @field_validator(
        "score_weight_jitter", "score_weight_shimmer",
        "score_weight_hnr", "score_weight_voiced",
        mode="before",
    )
    @classmethod
    def _weights_positive(cls, v: float) -> float:
        if float(v) < 0:
            raise ValueError("Score weights must be non-negative")
        return float(v)

    # ── Locale ────────────────────────────────────────────────────────────────
    default_locale: str = "pt-BR"    # "pt-BR" | "en"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — free on Lambda warm invocations."""
    return Settings()
