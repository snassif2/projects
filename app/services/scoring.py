"""
app/services/scoring.py
Converts a FeatureBundle into a VoiceAnalysisResult.

Scoring is a weighted rules engine (configurable via Settings).
All thresholds and weights come from config — never hardcoded here.
i18n: both PT-BR and EN messages are always generated.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.schemas import (
    ActionRequired,
    AmplitudeParameters,
    AnalysisStatus,
    ClinicalIndicators,
    FundamentalParameters,
    Gender,
    ParameterStatus,
    PathologyRisk,
    RiskLevel,
    SpectralAnalysis,
    VoiceAnalysisResult,
    VoiceStability,
)
from app.services.features import FeatureBundle

logger = logging.getLogger(__name__)


def score(bundle: FeatureBundle, settings: Settings) -> VoiceAnalysisResult:
    """
    Main entry point.
    Raises ValueError if bundle.f0 is None (caller must handle as 422).
    """
    if bundle.f0 is None:
        raise ValueError(
            "F0 extraction failed — audio is unanalysable. "
            "Ask the user to record again with more sustained phonation."
        )

    f0 = bundle.f0
    amp = bundle.amplitude
    spec = bundle.spectral
    hnr_feat = bundle.hnr

    # ── Gender heuristic ─────────────────────────────────────────────────────
    # Used only to contextualise F0 norms in the output label.
    # Does NOT affect the health score computation.
    gender = (
        Gender.FEMALE
        if f0.f0_mean_hz > settings.gender_f0_threshold_hz
        else Gender.MALE
    )

    # ── Individual parameter scores (0–10 each) ───────────────────────────────
    jitter_score = _score_jitter(f0.jitter_relative_pct, settings)
    shimmer_score = _score_shimmer(amp.shimmer_local_db, settings)
    hnr_score = _score_hnr(hnr_feat.hnr_db, settings)
    voiced_score = _score_voiced(f0.voiced_fraction_pct)

    # ── Weighted composite score ──────────────────────────────────────────────
    overall = (
        jitter_score  * settings.score_weight_jitter
        + shimmer_score * settings.score_weight_shimmer
        + hnr_score     * settings.score_weight_hnr
        + voiced_score  * settings.score_weight_voiced
    )
    overall = round(min(max(overall, 0.0), 10.0), 1)

    # ── Risk labels ───────────────────────────────────────────────────────────
    overall_risk = _risk_from_score(overall)
    jitter_status = (
        ParameterStatus.NORMAL
        if f0.jitter_relative_pct <= settings.jitter_normal_max_pct
        else ParameterStatus.ELEVATED
    )
    shimmer_status = (
        ParameterStatus.NORMAL
        if amp.shimmer_local_db <= settings.shimmer_normal_max_db
        else ParameterStatus.ELEVATED
    )
    hnr_status = (
        ParameterStatus.NORMAL
        if hnr_feat.hnr_db >= settings.hnr_normal_min_db
        else ParameterStatus.REDUCED
    )
    voice_stability = (
        VoiceStability.STABLE
        if f0.jitter_relative_pct <= settings.jitter_normal_max_pct
        else VoiceStability.UNSTABLE
    )

    # ── MPT classification ────────────────────────────────────────────────────
    mpt = bundle.duration_seconds
    if mpt >= settings.mpt_normal_min_seconds:
        mpt_status = ParameterStatus.NORMAL
    elif mpt >= settings.mpt_borderline_min_seconds:
        mpt_status = ParameterStatus.REDUCED   # borderline — reuses REDUCED
    else:
        mpt_status = ParameterStatus.ELEVATED  # low MPT — reuses ELEVATED as "flag"

    # ── i18n messages ─────────────────────────────────────────────────────────
    recs_en, msg_en, action = _build_messages_en(overall, overall_risk, jitter_status, shimmer_status, hnr_status, mpt, mpt_status)
    recs_pt, msg_pt, _ = _build_messages_pt(overall, overall_risk, jitter_status, shimmer_status, hnr_status, mpt, mpt_status)

    # ── Assemble result ───────────────────────────────────────────────────────
    return VoiceAnalysisResult(
        audio_id=str(uuid.uuid4()),
        analysis_timestamp=datetime.now(tz=timezone.utc),
        duration_seconds=bundle.duration_seconds,
        overall_health_score=overall,
        status=AnalysisStatus.COMPLETE,

        fundamental_parameters=FundamentalParameters(
            f0_mean_hz=f0.f0_mean_hz,
            f0_std_hz=f0.f0_std_hz,
            f0_min_hz=f0.f0_min_hz,
            f0_max_hz=f0.f0_max_hz,
            jitter_relative_pct=f0.jitter_relative_pct,
            voiced_fraction_pct=f0.voiced_fraction_pct,
            detected_gender=gender,
        ),
        amplitude_parameters=AmplitudeParameters(
            shimmer_local_db=amp.shimmer_local_db,
            rms_mean=amp.rms_mean,
            rms_std=amp.rms_std,
        ),
        spectral_analysis=SpectralAnalysis(
            centroid_hz=spec.centroid_hz,
            rolloff_hz=spec.rolloff_hz,
            bandwidth_hz=spec.bandwidth_hz,
            formant_peaks_hz=spec.formant_peaks_hz,
        ),
        clinical_indicators=ClinicalIndicators(
            hnr_db=hnr_feat.hnr_db,
            voice_stability=voice_stability,
            mpt_seconds=round(mpt, 1),
            mpt_status=mpt_status,
        ),
        pathology_risk=PathologyRisk(
            overall_risk=overall_risk,
            jitter_status=jitter_status,
            shimmer_status=shimmer_status,
            hnr_status=hnr_status,
        ),

        recommendations=recs_pt,          # default locale
        patient_message=msg_pt,
        action_required=action,
        recommendations_en=recs_en,
        patient_message_en=msg_en,
        recommendations_pt=recs_pt,
        patient_message_pt=msg_pt,
    )


# ── Sub-scorers (0–10) ────────────────────────────────────────────────────────

def _score_jitter(jitter_pct: float, s: Settings) -> float:
    """Lower jitter → higher score. Linear decay above threshold."""
    if jitter_pct <= s.jitter_normal_max_pct:
        return 10.0
    # At 2× threshold → 5.0; beyond → decays toward 0
    ratio = jitter_pct / s.jitter_normal_max_pct
    return max(0.0, 10.0 - (ratio - 1.0) * 5.0)


def _score_shimmer(shimmer_db: float, s: Settings) -> float:
    if shimmer_db <= s.shimmer_normal_max_db:
        return 10.0
    ratio = shimmer_db / s.shimmer_normal_max_db
    return max(0.0, 10.0 - (ratio - 1.0) * 5.0)


def _score_hnr(hnr_db: float, s: Settings) -> float:
    """Higher HNR → higher score."""
    if hnr_db >= s.hnr_normal_min_db:
        return 10.0
    # At 0 dB → 0; linear between 0 and threshold
    return max(0.0, (hnr_db / s.hnr_normal_min_db) * 10.0)


def _score_voiced(voiced_pct: float) -> float:
    """More voiced frames → higher score. Penalises breathy/interrupted phonation."""
    if voiced_pct >= 80.0:
        return 10.0
    if voiced_pct >= 50.0:
        return 5.0 + (voiced_pct - 50.0) / 6.0
    return max(0.0, voiced_pct / 5.0)


def _risk_from_score(score: float) -> RiskLevel:
    if score >= 7.0:
        return RiskLevel.LOW
    if score >= 5.0:
        return RiskLevel.MODERATE
    return RiskLevel.HIGH


# ── i18n message builders ─────────────────────────────────────────────────────

def _build_messages_en(
    score: float,
    risk: RiskLevel,
    jitter: ParameterStatus,
    shimmer: ParameterStatus,
    hnr: ParameterStatus,
    mpt: float,
    mpt_status: ParameterStatus,
) -> tuple[list[str], str, ActionRequired]:
    recs: list[str] = []

    if risk == RiskLevel.LOW:
        msg = "Your voice sounds healthy. Keep up good vocal habits."
        action = ActionRequired.NONE
        recs.append("Maintain regular vocal hydration (8+ glasses of water daily).")
        recs.append("Warm up your voice before extended singing or speaking.")

    elif risk == RiskLevel.MODERATE:
        msg = "Some signs of vocal fatigue were detected. Rest and monitor your voice."
        action = ActionRequired.MONITOR
        recs.append("Rest your voice for 24–48 hours and avoid whispering.")
        recs.append("Stay well hydrated and avoid caffeine and alcohol.")
        if jitter == ParameterStatus.ELEVATED:
            recs.append("Elevated pitch irregularity detected — gentle humming exercises may help.")
        if shimmer == ParameterStatus.ELEVATED:
            recs.append("Amplitude variation is above normal — consider a resonance check with your therapist.")
        if hnr == ParameterStatus.REDUCED:
            recs.append("Increased breathiness detected — avoid forced projection until this resolves.")

    else:  # HIGH
        msg = "Significant vocal irregularities detected. A professional evaluation is recommended."
        action = ActionRequired.CONSULT
        recs.append("Schedule a consultation with a voice therapist or ENT specialist.")
        recs.append("Avoid vocal strain, shouting, and whispering until evaluated.")
        recs.append("Do not self-medicate or attempt intensive vocal exercises without guidance.")
        if hnr == ParameterStatus.REDUCED:
            recs.append("Significant breathiness/roughness detected — this warrants clinical assessment.")

    # MPT note (added regardless of overall risk)
    if mpt_status == ParameterStatus.ELEVATED:  # low MPT (<10s)
        recs.append(f"Maximum phonation time ({mpt:.1f}s) is below normal (≥15s). This may indicate reduced respiratory support or glottic efficiency.")
    elif mpt_status == ParameterStatus.REDUCED:  # borderline (10–14s)
        recs.append(f"Maximum phonation time ({mpt:.1f}s) is borderline (normal ≥15s). Try to sustain for longer in your next recording.")

    recs.append(
        "⚠️ This screening is not a medical diagnosis. "
        "Always consult a qualified professional for clinical concerns."
    )
    return recs, msg, action


def _build_messages_pt(
    score: float,
    risk: RiskLevel,
    jitter: ParameterStatus,
    shimmer: ParameterStatus,
    hnr: ParameterStatus,
    mpt: float,
    mpt_status: ParameterStatus,
) -> tuple[list[str], str, ActionRequired]:
    recs: list[str] = []

    if risk == RiskLevel.LOW:
        msg = "Sua voz parece saudável. Continue mantendo bons hábitos vocais."
        action = ActionRequired.NONE
        recs.append("Mantenha a hidratação vocal adequada (8+ copos de água por dia).")
        recs.append("Faça aquecimento vocal antes de cantar ou falar por períodos prolongados.")

    elif risk == RiskLevel.MODERATE:
        msg = "Foram detectados sinais de cansaço vocal. Descanse e monitore sua voz."
        action = ActionRequired.MONITOR
        recs.append("Descanse a voz por 24–48 horas e evite sussurrar.")
        recs.append("Mantenha-se bem hidratado e evite cafeína e álcool.")
        if jitter == ParameterStatus.ELEVATED:
            recs.append("Irregularidade de altura detectada — exercícios suaves de ressonância podem ajudar.")
        if shimmer == ParameterStatus.ELEVATED:
            recs.append("Variação de amplitude acima do normal — considere uma avaliação de ressonância com seu terapeuta.")
        if hnr == ParameterStatus.REDUCED:
            recs.append("Soprosidade aumentada — evite projeção forçada até que isso se resolva.")

    else:  # HIGH
        msg = "Irregularidades vocais significativas detectadas. Uma avaliação profissional é recomendada."
        action = ActionRequired.CONSULT
        recs.append("Agende uma consulta com um fonoaudiólogo ou otorrinolaringologista.")
        recs.append("Evite esforço vocal, gritos e sussurros até ser avaliado.")
        recs.append("Não se automedique nem faça exercícios vocais intensos sem orientação.")
        if hnr == ParameterStatus.REDUCED:
            recs.append("Soprosidade/rouquidão significativa detectada — requer avaliação clínica.")

    # MPT note (added regardless of overall risk)
    if mpt_status == ParameterStatus.ELEVATED:  # low MPT (<10s)
        recs.append(f"Tempo máximo de fonação ({mpt:.1f}s) abaixo do esperado (≥15s). Pode indicar suporte respiratório reduzido ou ineficiência glótica.")
    elif mpt_status == ParameterStatus.REDUCED:  # borderline (10–14s)
        recs.append(f"Tempo máximo de fonação ({mpt:.1f}s) limítrofe (normal ≥15s). Tente sustentar por mais tempo na próxima gravação.")

    recs.append(
        "⚠️ Esta triagem não é um diagnóstico médico. "
        "Consulte sempre um profissional qualificado para questões clínicas."
    )
    return recs, msg, action
