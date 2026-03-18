"""
app/routers/analysis.py
Three endpoints:

  POST /upload-url   → issues a presigned S3 PUT URL and registers audio_id in DynamoDB
  GET  /result/{id}  → polls DynamoDB for analysis status / result
  GET  /config       → returns client-side limits so the frontend never hardcodes them

The analysis itself runs in a SEPARATE Lambda (analysis_handler.py) triggered by S3.
This router never calls librosa.
"""
from __future__ import annotations

import logging
import uuid

import boto3
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.schemas import (
    AnalysisStatus,
    ClientConfig,
    ResultResponse,
    UploadUrlRequest,
    UploadUrlResponse,
    VoiceAnalysisResult,
)
from app.services import store
from app.services.audio_io import validate_file_size, validate_mime_type

logger = logging.getLogger(__name__)
router = APIRouter()


# ── POST /upload-url ──────────────────────────────────────────────────────────

@router.post("/upload-url", response_model=UploadUrlResponse, status_code=201)
def request_upload_url(
    body: UploadUrlRequest,
    settings: Settings = Depends(get_settings),
) -> UploadUrlResponse:
    """
    1. Validates MIME type and file size against config limits.
    2. Generates a unique audio_id.
    3. Creates a presigned S3 PUT URL the browser will use to upload directly.
    4. Registers a PENDING placeholder in DynamoDB.
    5. Returns audio_id + presigned URL to the frontend.
    """
    # Validation — raises AudioValidationError (400) on failure
    validate_mime_type(body.mime_type, settings)
    validate_file_size(body.file_size_bytes, settings)

    audio_id = str(uuid.uuid4())

    # Derive a safe S3 key from the original filename extension
    from pathlib import Path
    original_ext = Path(body.filename).suffix or ".webm"
    s3_key = f"audio-intake/{audio_id}{original_ext}"

    # Generate presigned PUT URL
    s3_client = boto3.client("s3", region_name=settings.aws_region)
    try:
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": s3_key,
                "ContentType": body.mime_type,
            },
            ExpiresIn=settings.presigned_url_expiry,
        )
    except Exception as exc:
        logger.exception("Failed to generate presigned URL: %s", exc)
        raise HTTPException(status_code=502, detail="Could not generate upload URL.") from exc

    # Persist PENDING state so polling can start immediately
    store.put_pending(audio_id, settings)

    logger.info("upload-url issued: audio_id=%s key=%s", audio_id, s3_key)

    return UploadUrlResponse(
        audio_id=audio_id,
        upload_url=presigned_url,
        expires_in_seconds=settings.presigned_url_expiry,
    )


# ── GET /result/{audio_id} ────────────────────────────────────────────────────

@router.get("/result/{audio_id}", response_model=ResultResponse)
def get_result(
    audio_id: str,
    settings: Settings = Depends(get_settings),
) -> ResultResponse:
    """
    Frontend polls this until status is 'complete' or 'failed'.
    Typical analysis time: 1–3 seconds on Lambda.
    Recommended polling interval: 1s with exponential backoff up to 5s.
    """
    item = store.get_result(audio_id, settings)

    if item is None:
        raise HTTPException(status_code=404, detail="audio_id not found.")

    status = AnalysisStatus(item["status"])

    if status == AnalysisStatus.COMPLETE:
        result = VoiceAnalysisResult.model_validate_json(item["result"])
        return ResultResponse(audio_id=audio_id, status=status, result=result)

    if status == AnalysisStatus.FAILED:
        return ResultResponse(
            audio_id=audio_id,
            status=status,
            error_message=item.get("error", "Unknown error"),
        )

    # PENDING or PROCESSING — tell the client to keep polling
    return ResultResponse(audio_id=audio_id, status=status)


# ── GET /config ───────────────────────────────────────────────────────────────

@router.get("/config", response_model=ClientConfig)
def get_client_config(settings: Settings = Depends(get_settings)) -> ClientConfig:
    """
    The frontend reads this on load and never hardcodes audio limits.
    Changing VOZLAB_MAX_DURATION_SECONDS in the environment is enough to
    update both backend enforcement and frontend UX simultaneously.
    """
    return ClientConfig(
        max_duration_seconds=settings.max_duration_seconds,
        min_duration_seconds=settings.min_duration_seconds,
        max_file_size_bytes=settings.max_file_size_bytes,
        allowed_mime_types=settings.allowed_mime_types,
        default_locale=settings.default_locale,
    )
