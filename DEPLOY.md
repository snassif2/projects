# VozLab Deployment Guide

## Prerequisites Checklist
- [x] AWS CLI installed and configured
- [x] AWS account authenticated (user: samir, account: 983119018116)
- [ ] AWS SAM CLI installed
- [ ] Python 3.12 available

## Step-by-Step Deployment

### 1. Install AWS SAM CLI
Download and run: https://github.com/aws/aws-sam-cli/releases/latest/download/AWS_SAM_CLI_64_PY3.msi

After installation, **restart your terminal** and verify:
```bash
sam --version
```

### 2. Choose AWS Region
Recommended regions for Brazil:
- `us-east-1` (N. Virginia) - lowest latency to Brazil
- `sa-east-1` (São Paulo) - in Brazil, but more expensive

### 3. Build the Application
```bash
cd infra
sam build
```

This packages both Lambda functions with dependencies.

### 4. Deploy to AWS
```bash
sam deploy --guided
```

You'll be prompted for:
- **Stack Name**: `vozlab-voice-analysis` (or your choice)
- **AWS Region**: `us-east-1` (recommended)
- **Parameter CorsOrigins**: `["*"]` (for testing) or `["https://yourdomain.com"]` (production)
- **Confirm changes**: Y
- **Allow SAM CLI IAM role creation**: Y
- **Disable rollback**: N (keep rollback enabled)
- **Save arguments to samconfig.toml**: Y

### 5. Note the Outputs
After deployment completes, SAM will display:
```
Outputs
-----------------------------------------------------------------
ApiEndpoint: https://xxxxx.execute-api.us-east-1.amazonaws.com
AudioBucketName: vozlab-audio-intake-983119018116
ResultsTableName: vozlab-results
```

**Save the ApiEndpoint** - you'll need it for the frontend.

### 6. Test the API
```bash
# Health check
curl https://YOUR_API_ENDPOINT/health

# Get config
curl https://YOUR_API_ENDPOINT/config
```

### 7. Deploy Frontend
Update `frontend/index.html` line ~20 with your API endpoint:
```javascript
const API_BASE_URL = 'https://YOUR_API_ENDPOINT';
```

Then upload to S3 or host anywhere (GitHub Pages, Netlify, etc.)

## Costs Estimate
- **Lambda**: ~$0.20 per 1M requests (Free tier: 1M requests/month)
- **S3**: ~$0.023 per GB (Free tier: 5 GB/month)
- **DynamoDB**: ~$1.25 per million writes (Free tier: 25 GB storage)
- **API Gateway**: ~$1.00 per million requests (Free tier: 1M requests/month)

**Expected monthly cost for 1000 users**: < $1 (within free tier)

## Troubleshooting

### SAM build fails
- Ensure Python 3.12 is installed: `python --version`
- Check you're in the `infra/` directory

### Deployment fails - insufficient permissions
Your IAM user needs:
- CloudFormation full access
- Lambda full access
- S3 full access
- DynamoDB full access
- IAM role creation
- API Gateway full access

### Lambda timeout errors
Increase timeout in `infra/template.yaml`:
```yaml
AnalyzerFunction:
  Properties:
    Timeout: 60  # increase from 30
```

## Update Deployment
After code changes:
```bash
cd infra
sam build
sam deploy  # no --guided needed, uses saved config
```

## Delete Stack
To remove all resources:
```bash
sam delete --stack-name vozlab-voice-analysis
```

## Next Steps
1. Test with real audio recordings
2. Monitor CloudWatch Logs for errors
3. Set up CloudWatch alarms for Lambda errors
4. Configure custom domain for API Gateway
5. Add CloudFront for frontend hosting
