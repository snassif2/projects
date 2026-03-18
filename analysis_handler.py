"""
analysis_handler.py
AWS Lambda handler triggered by S3 ObjectCreated events.

This is a SEPARATE Lambda function from the API (app/main.py).
It imports parselmouth (audio analysis) — keeping the API Lambda lean.

Execution flow:
  1. S3 event arrives with bucket + key
  2. Download audio to /tmp via context manager
  3. Load + validate audio (duration gates)
  4. Extract features
  5. Score
  6. Write result to DynamoDB
  7. Delete audio from S3 (optional — lifecycle rule handles it anyway)

Lambda configuration recommended:
  - Memory: 512 MB (parselmouth + numpy need headroom)
  - Timeout: 30s (generous for 10s audio + cold start)
  - Handler: analysis_handler.handler
"""
from __future__ import annotations

import json
import logging
import urllib.parse

import boto3

# Lazy imports at module level are fine here — this Lambda is dedicated to analysis.
# If cold start becomes a bottleneck, move parselmouth imports inside the handler body.
from app.config import get_settings
from app.services import store
from app.services.audio_io import AudioValidationError, load_audio, s3_audio_as_tempfile
from app.services.features import extract_all
from app.services.scoring import score

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict, context: object) -> dict:  # noqa: ARG001
    """
    Entry point for the S3-triggered Lambda.
    Returns a dict for Lambda compatibility (not used by API Gateway).
    """
    settings = get_settings()
    processed = 0
    failed = 0

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        # S3 key may be URL-encoded
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        # audio_id is the UUID portion of the key: "audio-intake/{audio_id}.webm"
        audio_id = _extract_audio_id(key)
        if not audio_id:
            logger.warning("Could not parse audio_id from key=%s — skipping", key)
            continue

        logger.info("Processing audio_id=%s key=%s", audio_id, key)
        store.put_processing(audio_id, settings)

        try:
            with s3_audio_as_tempfile(bucket, key, settings.aws_region) as tmp_path:
                y, sr = load_audio(tmp_path, settings)

            bundle = extract_all(y, sr)
            result = score(bundle, settings)

            # Override audio_id so it matches the S3 key, not a new UUID from scoring
            result = result.model_copy(update={"audio_id": audio_id})

            store.put_result(result, settings)
            logger.info(
                "Analysis complete: audio_id=%s score=%.1f duration=%.2fs",
                audio_id, result.overall_health_score, bundle.duration_seconds,
            )
            processed += 1

            # Proactively delete from S3 (lifecycle rule is the backstop)
            _delete_s3_object(bucket, key, settings.aws_region)

        except AudioValidationError as exc:
            # Expected validation failures (too short, unanalysable) → FAILED status
            logger.warning("Validation error for audio_id=%s: %s", audio_id, exc.detail)
            store.put_failed(audio_id, exc.detail, settings)
            failed += 1

        except ValueError as exc:
            # F0 extraction returned None — unanalysable audio
            logger.warning("Unanalysable audio for audio_id=%s: %s", audio_id, exc)
            store.put_failed(audio_id, str(exc), settings)
            failed += 1

        except Exception as exc:
            # Unexpected errors — log fully, mark failed, never crash the Lambda
            logger.exception("Unexpected error for audio_id=%s: %s", audio_id, exc)
            store.put_failed(audio_id, f"Internal processing error: {type(exc).__name__}", settings)
            failed += 1

    return {"processed": processed, "failed": failed}


def _extract_audio_id(key: str) -> str | None:
    """
    "audio-intake/3f2504e0-4f89-11d3-9a0c-0305e82c3301.webm"
    → "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    """
    from pathlib import Path
    stem = Path(key).stem
    # Basic UUID format check
    if len(stem) == 36 and stem.count("-") == 4:
        return stem
    return None


def _delete_s3_object(bucket: str, key: str, region: str) -> None:
    """Best-effort S3 delete. The 24h lifecycle rule is the backstop."""
    try:
        boto3.client("s3", region_name=region).delete_object(Bucket=bucket, Key=key)
        logger.debug("S3 object deleted: %s/%s", bucket, key)
    except Exception as exc:
        logger.warning("Could not delete S3 object %s/%s: %s", bucket, key, exc)
