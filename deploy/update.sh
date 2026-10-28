#!/usr/bin/env bash
# Pull the latest code on the EC2 host and redeploy.
set -euo pipefail
cd "$HOME/app"
git pull
sudo docker compose up -d --build
sudo docker image prune -f
sudo docker compose ps
