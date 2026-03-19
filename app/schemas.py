"""
app/schemas.py
All request/response Pydantic models.
Replaces the previous bare Dict fields with strongly-typed nested models.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Annotated
from pydantic import BaseModel, Field, ConfigDict


# ── Enums ────────────────────────────────────────────────────────────────────

class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"

class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"

class ParameterStatus(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    REDUCED = "reduced"

class VoiceStability(str, Enum):
    STABLE = "stable"
    UNSTABLE = "unstable"

class AnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"

class ActionRequired(str, Enum):
    NONE = "none"
    MONITOR = "monitor"
    CONSULT = "consult"
    URGENT = "urgent"

class DDKStatus(str, Enum):
    NORMAL    = "normal"
    SLOW      = "slow"       # rate below normal range
    IRREGULAR = "irregular"  # CV above threshold


# ── Sub-models ────────────────────────────────────────────────────────────────

class FundamentalParameters(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    f0_mean_hz: Annotated[float, Field(ge=0, description="Mean fundamental frequency (Hz)")]
    f0_std_hz: Annotated[float, Field(ge=0, description="F0 standard deviation (Hz)")]
    f0_min_hz: Annotated[float, Field(ge=0)]
    f0_max_hz: Annotated[float, Field(ge=0)]
    jitter_relative_pct: Annotated[float, Field(ge=0, description="Relative jitter proxy (%)")]
    voiced_fraction_pct: Annotated[float, Field(ge=0, le=100, description="Voiced frames (%)")]
    detected_gender: Gender


class AmplitudeParameters(BaseModel):
    shimmer_local_db: Annotated[float, Field(ge=0, description="Praat local shimmer (dB)")]
    rms_mean: Annotated[float, Field(ge=0)]
    rms_std: Annotated[float, Field(ge=0)]


class SpectralAnalysis(BaseModel):
    centroid_hz: Annotated[float, Field(ge=0)]
    rolloff_hz: Annotated[float, Field(ge=0)]
    bandwidth_hz: Annotated[float, Field(ge=0)]
    # Up to 4 formant peak estimates (Hz). May be fewer if not detected.
    formant_peaks_hz: list[float] = Field(default_factory=list, max_length=4)


class ClinicalIndicators(BaseModel):
    hnr_db: float = Field(description="Harmonics-to-noise ratio (dB)")
    voice_stability: VoiceStability
    mpt_seconds: float = Field(ge=0, description="Maximum Phonation Time — duration of sustained voiced phonation (s)")
    mpt_status: ParameterStatus = Field(description="normal ≥15s | borderline 10–14s | reduced <10s")


class PathologyRisk(BaseModel):
    overall_risk: RiskLevel
    jitter_status: ParameterStatus
    shimmer_status: ParameterStatus
    hnr_status: ParameterStatus


class DDKAnalysis(BaseModel):
    """Populated only when recording_type == 'ddk'."""
    syllable_rate_hz:   float = Field(ge=0, description="Detected syllables per second")
    triad_rate_hz:      float = Field(ge=0, description="pa-ta-ka triads per second (rate / 3)")
    syllable_count:     int   = Field(ge=0, description="Total syllable peaks detected")
    regularity_cv_pct:  float = Field(ge=0, description="CV of inter-peak intervals (%)")
    ddk_status:         DDKStatus
    regularity_status:  ParameterStatus   # normal / reduced(borderline) / elevated(irregular)
    patient_message_pt: str
    recommendations_pt: list[str]


# ── Top-level result ──────────────────────────────────────────────────────────

class VoiceAnalysisResult(BaseModel):
    """
    Complete analysis result stored in DynamoDB and returned to the frontend.
    All nested objects are fully typed — no bare Dict anywhere.
    """
    audio_id: str
    analysis_timestamp: datetime
    duration_seconds: Annotated[float, Field(ge=0)]
    overall_health_score: Annotated[float, Field(ge=0, le=10)]
    status: AnalysisStatus

    fundamental_parameters: FundamentalParameters
    amplitude_parameters: AmplitudeParameters
    spectral_analysis: SpectralAnalysis
    clinical_indicators: ClinicalIndicators
    pathology_risk: PathologyRisk

    recommendations: list[str]
    patient_message: str
    action_required: ActionRequired

    # i18n: both locales always present so the frontend can switch without re-fetching
    recommendations_en: list[str]
    patient_message_en: str
    recommendations_pt: list[str]
    patient_message_pt: str

    # DDK — only populated when recording_type == "ddk"
    recording_type: str = "phonation"   # "phonation" | "speech" | "ddk"
    ddk_analysis: DDKAnalysis | None = None


# ── Narrative / LLM schemas ───────────────────────────────────────────────

class Anamnesis(BaseModel):
    """Brief pre-recording patient context collected by the frontend."""
    sexo: str = Field(description="masculino | feminino")
    idade: int = Field(ge=5, le=120, description="Age in years")
    queixa: str = Field(default="", max_length=300, description="Main complaint (optional)")


class GRBASScore(BaseModel):
    G: int = Field(ge=0, le=3, description="Overall grade")
    R: int = Field(ge=0, le=3, description="Roughness")
    B: int = Field(ge=0, le=3, description="Breathiness")
    A: int = Field(ge=0, le=3, description="Asthenia")
    S: int = Field(ge=0, le=3, description="Strain")


class NarrativeRequest(BaseModel):
    """Body for POST /narrative"""
    anamnesis: Anamnesis
    phonation: VoiceAnalysisResult
    speech:    VoiceAnalysisResult
    ddk:       VoiceAnalysisResult


class NarrativeResponse(BaseModel):
    """Returned by POST /narrative"""
    narrative_pt:    str
    grbas:           GRBASScore
    action_required: ActionRequired


# ── API request / response wrappers ──────────────────────────────────────────

class UploadUrlRequest(BaseModel):
    """Body for POST /upload-url"""
    filename: str = Field(description="Original filename from the browser")
    mime_type: str = Field(description="MIME type the browser will use to upload")
    file_size_bytes: int = Field(gt=0)
    recording_type: str = Field(default="phonation", description="phonation | speech | ddk")


class UploadUrlResponse(BaseModel):
    """Returned by POST /upload-url"""
    audio_id: str
    upload_url: str = Field(description="Presigned S3 PUT URL")
    expires_in_seconds: int


class ResultResponse(BaseModel):
    """Returned by GET /result/{audio_id}"""
    audio_id: str
    status: AnalysisStatus
    # Only populated when status=complete
    result: VoiceAnalysisResult | None = None
    # Only populated when status=failed
    error_message: str | None = None


class ClientConfig(BaseModel):
    """
    Returned by GET /config.
    Frontend reads this on load — never hardcodes limits.
    """
    max_duration_seconds: int
    min_duration_seconds: int
    max_file_size_bytes: int
    allowed_mime_types: list[str]
    default_locale: str
