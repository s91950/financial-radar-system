#!/bin/bash
# Oracle Cloud VM 初始化腳本
# 在 VM 上執行：bash setup.sh

set -e
echo "=== 開始安裝環境 ==="

# 更新系統
sudo apt-get update && sudo apt-get upgrade -y

# 安裝 Python 3.10+
sudo apt-get install -y python3 python3-pip python3-venv

# 安裝 Node.js 18
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# 安裝 nginx + git
sudo apt-get install -y nginx git

# 建立應用程式目錄
sudo mkdir -p /opt/financial-radar
sudo chown ubuntu:ubuntu /opt/financial-radar

echo "=== 環境安裝完成 ==="
python3 --version
node --version
nginx -v
