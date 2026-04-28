#!/bin/bash
# 以 root 執行，不需要 sudo
set -e

echo "=== 更新 apt ==="
apt-get update -qq

echo "=== 安裝依賴 ==="
apt-get install -y ca-certificates curl gnupg lsb-release -qq

echo "=== 加入 Docker GPG key ==="
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "=== 加入 Docker apt repo ==="
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "=== 安裝 Docker Engine ==="
apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -qq

echo "=== 設定一般使用者可用 docker ==="
NORMAL_USER=$(getent passwd 1000 | cut -d: -f1)
if [ -n "$NORMAL_USER" ]; then
  usermod -aG docker "$NORMAL_USER"
  echo "加入 docker group: $NORMAL_USER"
fi

echo "=== 設定 sudo NOPASSWD（方便後續操作）==="
echo "%sudo ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/nopasswd
chmod 440 /etc/sudoers.d/nopasswd

echo "=== 啟動 dockerd ==="
service docker start || true

echo "=== 版本確認 ==="
docker --version
docker compose version

echo "=== Done ==="
