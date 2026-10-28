#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 EC2 instance.
# Usage: bash setup_ec2.sh [REPO_URL]
set -euo pipefail

REPO_URL="${1:-https://github.com/traveller318/temp.git}"
APP_DIR="$HOME/app"

echo "==> Adding 2 GB swap (small instances run out of RAM during the build)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "==> Installing Docker, Compose and git"
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

echo "==> Getting the code"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull
else
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [ ! -f .env ]; then
  echo "==> Creating .env"
  read -rsp "Paste your Groq API key (input hidden): " GROQ_KEY
  echo
  cat > .env <<ENV
GROQ_API_KEY=${GROQ_KEY}
GROQ_MODEL=openai/gpt-oss-20b
LLM_PROVIDER=groq
ENV
  chmod 600 .env
fi

echo "==> Building and starting (first build takes 10-20 minutes)"
sudo docker compose up -d --build

PUBLIC_IP=$(curl -s https://checkip.amazonaws.com || echo "<EC2_PUBLIC_IP>")
echo
echo "Done. The API needs about a minute to load the index, then open:"
echo "  UI:  http://${PUBLIC_IP}/"
echo "  API: http://${PUBLIC_IP}:8000/docs"
