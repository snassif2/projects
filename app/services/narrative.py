"""
app/services/narrative.py
LLM-powered clinical narrative synthesis via Claude Haiku.

Single API call that receives all three acoustic result objects + brief anamnesis
and returns:
  - narrative_pt : 3-4 sentence clinical assessment in PT-BR
  - grbas        : estimated perceptual G/R/B/A/S scores (0–3)
  - action_required : none | monitor | consult | urgent

Designed for claude-haiku-4-5 (~$0.001/call).
Graceful degradation: returns None if the API key is absent or the call fails.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import anthropic

from app.schemas import (
    ActionRequired,
    GRBASScore,
    NarrativeRequest,
    NarrativeResponse,
)

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a clinical assistant supporting Brazilian speech-language pathologists (fonoaudiólogos).
You receive structured acoustic voice screening data and produce a brief clinical summary.

Rules:
- Write ONLY in Brazilian Portuguese.
- Keep the narrative 3-4 sentences: summarise the main findings, link them clinically, give a clear direction.
- GRBAS scores (0=normal, 1=mild, 2=moderate, 3=severe) must be consistent with the acoustic data.
- Do NOT diagnose — screen and recommend referral if warranted.
- Always end with a short disclaimer sentence.
- Respond ONLY with a valid JSON object — no markdown fences, no extra text.

JSON schema:
{
  "narrative_pt": "string",
  "grbas": {"G": 0-3, "R": 0-3, "B": 0-3, "A": 0-3, "S": 0-3},
  "action_required": "none" | "monitor" | "consult" | "urgent"
}"""


def _summarise(result: "NarrativeRequest") -> str:
    """Build a compact, token-efficient prompt from the three result objects."""
    a = result.anamnesis
    ph = result.phonation
    sp = result.speech
    dk = result.ddk

    def _params(r) -> str:
        fp = r.fundamental_parameters
        am = r.amplitude_parameters
        ci = r.clinical_indicators
        pr = r.pathology_risk
        return (
            f"F0 {fp.f0_mean_hz:.0f} Hz, jitter {fp.jitter_relative_pct:.2f}% ({pr.jitter_status}), "
            f"shimmer {am.shimmer_local_db:.2f} dB ({pr.shimmer_status}), "
            f"HNR {ci.hnr_db:.1f} dB ({pr.hnr_status}), "
            f"score {r.overall_health_score}/10 ({pr.overall_risk} risk)"
        )

    ddk_line = ""
    if dk.ddk_analysis:
        d = dk.ddk_analysis
        ddk_line = (
            f"\nDDK (/pa-ta-ka/): {d.syllable_rate_hz:.1f} síl/s ({d.ddk_status}), "
            f"CV {d.regularity_cv_pct:.0f}% ({d.regularity_status})."
        )

    complaint = a.queixa.strip() or "não relatada"
    mpt = ph.clinical_indicators
    return (
        f"Paciente: {a.sexo}, {a.idade} anos. Queixa principal: {complaint}.\n"
        f"Fonação sustentada (MPT {mpt.mpt_seconds:.1f}s, {mpt.mpt_status}): {_params(ph)}.\n"
        f"Fala contínua (CAPE-V): {_params(sp)}."
        f"{ddk_line}"
    )


def generate(request: NarrativeRequest, api_key: str, model: str) -> Optional[NarrativeResponse]:
    """
    Call Claude Haiku and return a NarrativeResponse, or None on any failure.
    """
    if not api_key:
        logger.warning("VOZLAB_ANTHROPIC_API_KEY not set — skipping narrative generation")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _summarise(request)

    try:
        message = client.messages.create(
            model=model,
            max_tokens=400,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)

        grbas = GRBASScore(
            G=int(data["grbas"]["G"]),
            R=int(data["grbas"]["R"]),
            B=int(data["grbas"]["B"]),
            A=int(data["grbas"]["A"]),
            S=int(data["grbas"]["S"]),
        )
        return NarrativeResponse(
            narrative_pt=data["narrative_pt"],
            grbas=grbas,
            action_required=ActionRequired(data["action_required"]),
        )

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Narrative JSON parse failed: %s — raw: %.200s", exc, raw if 'raw' in dir() else '')
        return None
    except anthropic.APIError as exc:
        logger.warning("Anthropic API error: %s", exc)
        return None
    except Exception as exc:
        logger.exception("Unexpected error in narrative.generate: %s", exc)
        return None
