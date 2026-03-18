# VozLab — Voice Screening API v2

Modular voice triage backend on AWS serverless + S3 + DynamoDB.  
Bilingual (PT-BR / EN). No Docker. No ffmpeg.

---

## Architecture

```
Browser (S3 + CloudFront)
    │
    ├─ GET  /config          → Lambda (API)   ← frontend reads limits on load
    │
    ├─ POST /upload-url      → Lambda (API)
    │       validates MIME + size
    │       writes PENDING to DynamoDB
    │       returns { audio_id, presigned_PUT_url }
    │
    ├─ PUT  <presigned_url>  → S3 (audio-intake/)
    │       browser uploads directly — no Lambda in the path
    │
    │       S3 ObjectCreated event fires:
    │
    ├─ S3 event ─────────────► Lambda (Analyzer)
    │       downloads audio from S3 to /tmp
    │       load_audio() → trim + duration guard
    │       extract_all() → F0 / amplitude / spectral / HNR
    │       score()       → health score + i18n messages
    │       writes COMPLETE + result JSON to DynamoDB
    │       deletes S3 object (lifecycle rule is backstop)
    │
    └─ GET  /result/{id}     → Lambda (API)
            polls DynamoDB
            returns { status, result? }
```

## AWS Resources

| Resource | Purpose | Retention |
|---|---|---|
| S3 `vozlab-audio-intake` | Temporary audio storage | 24h lifecycle |
| DynamoDB `vozlab-results` | Analysis results | 24h TTL |
| Lambda `vozlab-api` | Presigned URL + result polling | — |
| Lambda `vozlab-analyzer` | Audio analysis (librosa) | — |
| API Gateway HTTP API | Routes to `vozlab-api` | — |

---

## Project Structure

```
vozlab/
├── app/
│   ├── main.py                  FastAPI app factory + Mangum Lambda handler
│   ├── config.py                All settings via VOZLAB_* env vars
│   ├── schemas.py               Fully-typed Pydantic models (no bare Dict)
│   ├── routers/
│   │   └── analysis.py          POST /upload-url  GET /result/:id  GET /config
│   └── services/
│       ├── audio_io.py          MIME validation, S3 download, librosa load, duration guards
│       ├── scoring.py           Weighted health score + PT/EN messages
│       ├── store.py             DynamoDB read/write (pending/processing/complete/failed)
│       └── features/
│           ├── __init__.py      Orchestrates all extractors → FeatureBundle
│           ├── f0.py            pyin F0 + jitter proxy
│           ├── amplitude.py     RMS shimmer proxy
│           ├── spectral.py      centroid / rolloff / bandwidth / formant peaks
│           └── hnr.py           Autocorrelation HNR
│
├── analysis_handler.py          S3-triggered Lambda entry point
├── frontend/
│   └── index.html               Bilingual SPA — MIME negotiation, 10s cap, polling
│
├── tests/
│   ├── conftest.py              Synthetic audio fixtures
│   ├── test_features/test_f0.py
│   ├── test_scoring.py          Covers all 4 original bugs
│   └── test_api.py
│
├── infra/
│   └── template.yaml            AWS SAM IaC (2 Lambdas + S3 + DynamoDB)
│
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## Bugs Fixed from v1

| # | Bug | Fix |
|---|---|---|
| 7.1 | Frontend sent `.webm`, backend rejected it → every real recording failed silently | `audio/webm` added to allowlist; browser negotiates supported MIME before recording |
| 7.2 | `NameError: f0_male` in scoring → every analysis returned 500 | String keys `'f0_male'`/`'f0_female'` used correctly; covered by `test_scoring.py` |
| 7.3 | `except Exception` swallowed `HTTPException` → validation errors surfaced as 500 | `HTTPException`/`AudioValidationError` propagated cleanly; generic handler is last resort only |
| 7.4 | `tmp_path` used before assignment in `finally` | Context manager in `s3_audio_as_tempfile` guarantees cleanup without `os.unlink` |

---

## Local Development

```bash
# 1 — Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 2 — Configure
cp .env.example .env
# Edit .env: set VOZLAB_AWS_REGION, VOZLAB_S3_BUCKET, VOZLAB_DYNAMODB_TABLE
# For local dev without AWS, mock boto3 calls or use LocalStack

# 3 — Run API
uvicorn app.main:app --reload --port 8000

# 4 — Run tests
pytest tests/ -v
```

## Deploy to AWS

```bash
# Requires AWS SAM CLI
cd infra
sam build
sam deploy --guided
# Follow prompts — sets CorsOrigins to your CloudFront domain
```

---

## Key Design Decisions

**No ffmpeg** — MIME type is negotiated at the browser before recording starts
(`MediaRecorder.isTypeSupported`). The server only receives formats librosa handles natively on Linux.

**Two Lambdas, single repo** — `vozlab-api` stays lean (no librosa import).
`vozlab-analyzer` carries the heavy deps but only runs when audio arrives.

**Config → frontend** — `GET /config` exposes all limits so the frontend
never hardcodes them. Changing `VOZLAB_MAX_DURATION_SECONDS` in Lambda env
updates both server enforcement and UI simultaneously.

**i18n** — Both PT-BR and EN messages are always generated and stored.
The frontend switches language client-side without re-fetching.
