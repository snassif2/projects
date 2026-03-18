"""
app/services/store.py
DynamoDB read/write for analysis results.

Item schema:
    PK: audio_id (str)
    status: AnalysisStatus
    result: JSON string of VoiceAnalysisResult (when complete)
    error: str (when failed)
    ttl: int (Unix epoch — DynamoDB auto-deletes after 24h)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.config import Settings
from app.schemas import AnalysisStatus, VoiceAnalysisResult

logger = logging.getLogger(__name__)


def _table(settings: Settings):
    """Lazy DynamoDB Table resource — cheap on warm Lambda calls."""
    ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
    return ddb.Table(settings.dynamodb_table)


def put_pending(audio_id: str, settings: Settings) -> None:
    """Write a PENDING placeholder as soon as the presigned URL is issued."""
    ttl = int(time.time()) + settings.result_ttl_seconds
    _table(settings).put_item(Item={
        "audio_id": audio_id,
        "status": AnalysisStatus.PENDING.value,
        "ttl": ttl,
    })
    logger.debug("DynamoDB: put_pending audio_id=%s", audio_id)


def put_processing(audio_id: str, settings: Settings) -> None:
    """Mark as PROCESSING when the analysis Lambda picks up the S3 event."""
    _table(settings).update_item(
        Key={"audio_id": audio_id},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": AnalysisStatus.PROCESSING.value},
    )


def put_result(result: VoiceAnalysisResult, settings: Settings) -> None:
    """Write the completed result JSON."""
    # Pydantic serialises datetime → ISO string automatically
    result_json = result.model_dump_json()
    _table(settings).update_item(
        Key={"audio_id": result.audio_id},
        UpdateExpression="SET #s = :s, #r = :r",
        ExpressionAttributeNames={"#s": "status", "#r": "result"},
        ExpressionAttributeValues={
            ":s": AnalysisStatus.COMPLETE.value,
            ":r": result_json,
        },
    )
    logger.info("DynamoDB: put_result audio_id=%s score=%.1f", result.audio_id, result.overall_health_score)


def put_failed(audio_id: str, error: str, settings: Settings) -> None:
    """Write a FAILED status with the error message."""
    _table(settings).update_item(
        Key={"audio_id": audio_id},
        UpdateExpression="SET #s = :s, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": AnalysisStatus.FAILED.value,
            ":e": error,
        },
    )
    logger.warning("DynamoDB: put_failed audio_id=%s error=%s", audio_id, error)


def get_result(audio_id: str, settings: Settings) -> dict | None:
    """
    Fetch the item for audio_id.
    Returns the raw DynamoDB item dict, or None if not found.
    """
    try:
        response = _table(settings).get_item(Key={"audio_id": audio_id})
    except ClientError as exc:
        logger.error("DynamoDB get_item failed: %s", exc)
        return None

    return response.get("Item")
