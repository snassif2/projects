# VozLab Quick Start

## Local Development Setup

### 1. Install Dependencies
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Configure Environment
```bash
copy .env.example .env
# Edit .env with your AWS credentials and settings
```

### 3. Run API Locally
```bash
uvicorn app.main:app --reload --port 8000
```

Visit: http://localhost:8000/docs

### 4. Run Tests
```bash
pytest tests/ -v
```

## AWS Deployment

### Prerequisites
- AWS CLI configured
- AWS SAM CLI installed

### Deploy
```bash
cd infra
sam build
sam deploy --guided
```

Follow the prompts to configure:
- Stack name: `vozlab-voice-analysis`
- AWS Region: your preferred region
- CorsOrigins: `["*"]` for testing, or your domain for production

### Post-Deployment
1. Note the API endpoint from outputs
2. Upload `frontend/index.html` to S3 + CloudFront
3. Update frontend to point to your API endpoint

## Project Structure
```
voicetest/
├── app/                    # Main application
│   ├── routers/           # API endpoints
│   ├── services/          # Business logic
│   │   └── features/      # Audio feature extraction
│   ├── main.py            # FastAPI app
│   ├── config.py          # Settings
│   └── schemas.py         # Data models
├── analysis_handler.py    # S3-triggered Lambda
├── frontend/              # Web UI
├── infra/                 # AWS SAM template
└── tests/                 # Test suite
```

## Common Issues

### Import errors
Make sure you're in the project root and the virtual environment is activated.

### AWS credentials
Set environment variables or use `aws configure`.

### librosa installation
On Windows, you may need Visual C++ build tools.
