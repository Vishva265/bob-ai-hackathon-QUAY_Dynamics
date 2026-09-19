#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "    QUAY Port Operations - AWS Docker Deployment       "
echo "========================================================"

# 1. Install Docker & Docker Compose if not already present
if ! command -v docker &>/dev/null; then
    echo "[*] Installing Docker..."
    if command -v dnf &>/dev/null; then
        # Amazon Linux 2023 / Fedora
        sudo dnf update -y
        sudo dnf install -y docker git
        sudo systemctl enable --now docker
        sudo usermod -aG docker "$USER" || true
        # Install Docker Compose plugin
        sudo mkdir -p /usr/local/lib/docker/cli-plugins
        sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) -o /usr/local/lib/docker/cli-plugins/docker-compose
        sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    elif command -v apt-get &>/dev/null; then
        # Ubuntu / Debian
        sudo apt-get update -y
        sudo apt-get install -y docker.io docker-compose-v2 git curl
        sudo systemctl enable --now docker
        sudo usermod -aG docker "$USER" || true
    fi
fi

# Ensure docker service is running
sudo systemctl start docker || true

# 2. Clone or update repository
APP_DIR="/opt/bobathon"
REPO_URL="https://github.com/VASUVAGHASIA/bobathon.git"
BRANCH="${DEPLOY_BRANCH:-main}"

if [ -d "$APP_DIR/.git" ]; then
    echo "[*] Updating existing repository in $APP_DIR..."
    cd "$APP_DIR"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    echo "[*] Cloning repository into $APP_DIR..."
    sudo mkdir -p "$APP_DIR"
    sudo chown -R "$USER:$USER" "$APP_DIR"
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

cd "$APP_DIR/src"

# 3. Create .env with WatsonX credentials if missing
if [ ! -f .env ]; then
    echo "[*] Writing production .env..."
    cat << 'EOF' > .env
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
EOF
fi

# 4. Build and start containers
echo "[*] Building and starting Docker containers..."
sudo docker compose -f compose.prod.yaml down || true
sudo docker compose -f compose.prod.yaml up -d --build

# 5. Wait for readiness
echo "[*] Waiting for application to initialize..."
READY=0
for i in $(seq 1 40); do
    if curl -s -f http://127.0.0.1:8000/api/v1/ready &>/dev/null; then
        echo "[+] Backend API is ready!"
        READY=1
        break
    fi
    echo "    Waiting for backend startup (attempt $i/40)..."
    sleep 3
done

if [ "$READY" -ne 1 ]; then
    echo "[!] Warning: Backend healthcheck didn't respond within 120s. Checking logs:"
    sudo docker compose -f compose.prod.yaml logs backend --tail 40
fi

# 6. Retrieve and display public IP
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || curl -s https://checkip.amazonaws.com || echo "localhost")

echo ""
echo "========================================================"
echo "           DEPLOYMENT COMPLETE!                         "
echo "========================================================"
echo " Public Application URL: http://${PUBLIC_IP}"
echo " Backend Health Check:  http://${PUBLIC_IP}:8000/api/v1/ready"
echo " Interactive API Docs:  http://${PUBLIC_IP}/docs"
echo "========================================================"
