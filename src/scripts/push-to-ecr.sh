#!/usr/bin/env bash
# ==============================================================================
# QUAY Port Operations - Push Images to Amazon Elastic Container Registry (ECR)
# Can be run in AWS CloudShell or local terminal with AWS CLI
# ==============================================================================
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || echo 'us-east-1')}"
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "========================================================"
echo " Pushing QUAY Docker Images to Amazon ECR"
echo " AWS Account:  $ACCOUNT_ID"
echo " Region:       $REGION"
echo " Registry:     $ECR_REGISTRY"
echo "========================================================"

# 1. Login to ECR
echo "[*] Authenticating Docker with ECR..."
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

# 2. Create Repositories if needed
for REPO in quay-backend quay-frontend; do
    if ! aws ecr describe-repositories --region "$REGION" --repository-names "$REPO" &>/dev/null; then
        echo "[*] Creating repository: $REPO..."
        aws ecr create-repository --region "$REGION" --repository-name "$REPO" >/dev/null
    fi
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 3. Build & Tag Backend
echo "[*] Building and tagging Backend image..."
docker build -t quay-backend -f backend/Dockerfile .
docker tag quay-backend:latest "${ECR_REGISTRY}/quay-backend:latest"

# 4. Build & Tag Frontend
echo "[*] Building and tagging Frontend image..."
docker build -t quay-frontend -f frontend/Dockerfile .
docker tag quay-frontend:latest "${ECR_REGISTRY}/quay-frontend:latest"

# 5. Push Images
echo "[*] Pushing Backend to ECR..."
docker push "${ECR_REGISTRY}/quay-backend:latest"

echo "[*] Pushing Frontend to ECR..."
docker push "${ECR_REGISTRY}/quay-frontend:latest"

echo ""
echo "========================================================"
echo "    IMAGES SUCCESSFULLY PUSHED TO ECR!                  "
echo "========================================================"
echo " Backend Image URI:  ${ECR_REGISTRY}/quay-backend:latest"
echo " Frontend Image URI: ${ECR_REGISTRY}/quay-frontend:latest"
echo ""
echo " You can now select these images in AWS App Runner or ECS!"
echo "========================================================"
