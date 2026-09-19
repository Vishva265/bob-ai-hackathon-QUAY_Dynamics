#!/usr/bin/env bash
# ==============================================================================
# QUAY Port Operations - 1-Click AWS EC2 Docker Deployment Script
# Execute this directly in AWS CloudShell (open in your Chrome tab)
# ==============================================================================
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || echo 'us-east-1')}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
KEY_NAME="${KEY_NAME:-}"

echo "========================================================"
echo " Launching QUAY Port Operations Docker host in AWS"
echo " Region:        $REGION"
echo " Instance Type: $INSTANCE_TYPE"
echo "========================================================"

# 1. Locate VPC and Subnet
VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text)
if [ "$VPC_ID" == "None" ] || [ -z "$VPC_ID" ]; then
    VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --query "Vpcs[0].VpcId" --output text)
fi
echo "[+] Using VPC: $VPC_ID"

# 2. Setup Security Group
SG_NAME="quay-docker-sg"
SG_ID=$(aws ec2 describe-security-groups --region "$REGION" --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo "None")

if [ "$SG_ID" == "None" ] || [ -z "$SG_ID" ]; then
    echo "[*] Creating Security Group: $SG_NAME..."
    SG_ID=$(aws ec2 create-security-group \
        --region "$REGION" \
        --group-name "$SG_NAME" \
        --description "Security group for QUAY Docker deployment (HTTP/HTTPS/API)" \
        --vpc-id "$VPC_ID" \
        --query "GroupId" --output text)
    
    echo "[*] Adding firewall rules..."
    aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0
    aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" --protocol tcp --port 8000 --cidr 0.0.0.0/0
    aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" --protocol tcp --port 22 --cidr 0.0.0.0/0
    aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" --protocol tcp --port 443 --cidr 0.0.0.0/0
else
    echo "[+] Found existing Security Group: $SG_ID"
fi

# 3. Get latest Amazon Linux 2023 AMI
AMI_ID=$(aws ssm get-parameters --region "$REGION" --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query "Parameters[0].Value" --output text)
echo "[+] Using AMI: $AMI_ID"

# 4. Prepare User Data Script
USER_DATA=$(cat << 'EOF' | base64 | tr -d '\n'
#!/bin/bash
dnf update -y
dnf install -y docker git
systemctl enable --now docker
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

mkdir -p /opt/bobathon
git clone -b main https://github.com/VASUVAGHASIA/bobathon.git /opt/bobathon
cd /opt/bobathon/src

cat << 'ENVFILE' > .env
EXPLANATION_MODE=watsonx
WATSONX_APIKEY=YukTZOzF7nxBYNIaUrXgN22Q6NIyBe7NjYYuT1oO2y5p
WATSONX_PROJECT_ID=f41e2554-7c4c-4dcb-826f-c9c87d1cafcb
WATSONX_MODEL_ID=ibm/granite-4-h-small
WATSONX_API_VERSION=2025-10-25
WATSONX_URL=https://eu-de.ml.cloud.ibm.com
APP_ENV=development
AUTO_MIGRATE=true
DEMO_SEED_ON_START=true
MODEL_DIRECTORY=/workspace/demo/seed/models
EVALUATION_DIRECTORY=/workspace/demo/recorded
LIVE_DEMO_ENABLED=true
OPERATOR_API_KEY=quay-operator-key-production-2026-quay
CORS_ORIGINS=http://localhost,http://localhost:80,http://127.0.0.1
READINESS_REQUIRE_MODEL=true
READINESS_REQUIRE_DATA=true
ENVFILE

docker compose -f compose.prod.yaml up -d --build
EOF
)

# 5. Launch Instance
echo "[*] Launching EC2 instance ($INSTANCE_TYPE)..."
INSTANCE_ARGS=(
    --region "$REGION"
    --image-id "$AMI_ID"
    --instance-type "$INSTANCE_TYPE"
    --security-group-ids "$SG_ID"
    --user-data "$USER_DATA"
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=QUAY-PortOps-Docker}]"
    --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":25,\"VolumeType\":\"gp3\"}}]"
)

if [ -n "$KEY_NAME" ]; then
    INSTANCE_ARGS+=(--key-name "$KEY_NAME")
fi

INSTANCE_ID=$(aws ec2 run-instances "${INSTANCE_ARGS[@]}" --query "Instances[0].InstanceId" --output text)
echo "[+] Instance created: $INSTANCE_ID"

echo "[*] Waiting for instance to obtain public IP..."
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"

PUBLIC_IP=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" --query "Reservations[0].Instances[0].PublicIpAddress" --output text)

echo ""
echo "========================================================"
echo "    AWS EC2 DOCKER HOST SUCCESSFULLY LAUNCHED!         "
echo "========================================================"
echo " Instance ID: $INSTANCE_ID"
echo " Public IP:   $PUBLIC_IP"
echo ""
echo " Live Application URL: http://${PUBLIC_IP}"
echo " API Docs URL:         http://${PUBLIC_IP}/docs"
echo " Readiness Probe:      http://${PUBLIC_IP}:8000/api/v1/ready"
echo ""
echo " Note: The Docker containers take ~2 minutes to download,"
echo " build, and seed the demo data. Check the URL shortly!"
echo "========================================================"
