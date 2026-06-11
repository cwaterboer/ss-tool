#!/bin/bash
# Automated push and redeploy script - run after docker build completes

set -e

echo "========================================"
echo "Step 1: Push Docker Image to GCR"
echo "========================================"
docker push gcr.io/ss-tool-498115/fpa-web:latest

echo ""
echo "========================================"
echo "Step 2: Redeploy to Cloud Run"
echo "========================================"
gcloud run deploy fpa-web \
  --image gcr.io/ss-tool-498115/fpa-web:latest \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --set-cloudsql-instances ss-tool-498115:europe-west1:fpa-postgres \
  --service-account fpa-app@ss-tool-498115.iam.gserviceaccount.com \
  --memory 1Gi \
  --cpu 1 \
  --timeout 600 \
  --cpu-boost \
  --set-env-vars="DJANGO_SETTINGS_MODULE=config.settings.gcp,SECRET_KEY=5-9zvrsp^xc3efce)3y0s&^)f5)_2cpo@2^tjl$nhwbrcz8)ce,POSTGRES_DB=fpa_db,POSTGRES_USER=adminuser,POSTGRES_PASSWORD=jJX+ZENtVVR+bWaeZWdTqfCVjeXFKUfI,POSTGRES_HOST=/cloudsql/ss-tool-498115:europe-west1:fpa-postgres,REDIS_URL=redis://10.112.227.243:6379/0,USE_GCS=true,GCS_BUCKET_NAME=ss-tool-fpa-media,GCP_PROJECT_ID=ss-tool-498115,SECURE_SSL_REDIRECT=false"

echo ""
echo "========================================"
echo "Deployment Complete!"
echo "========================================"
echo "Service URL: https://fpa-web-369870387328.europe-west1.run.app"
echo ""
echo "Next: Test with a sample scan"
echo "1. Login at https://fpa-web-369870387328.europe-west1.run.app/accounts/login/"
echo "2. Create a site and upload a video"
echo "3. Monitor GPU worker: gcloud compute ssh fpa-gpu-worker --zone=europe-west1-c --command='sudo journalctl -u fpa-gpu-worker -f'"
