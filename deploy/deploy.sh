#!/bin/bash
# 部署/更新腳本
# 首次執行：bash deploy.sh
# 之後更新：bash deploy.sh

set -e
APP_DIR="/opt/financial-radar"
REPO="https://github.com/s91950/financial-radar-system.git"

echo "=== 拉取最新程式碼 ==="
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR" && git pull
else
    git clone "$REPO" "$APP_DIR"
    cd "$APP_DIR"
fi

echo "=== 安裝 Python 套件 ==="
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

echo "=== 建置前端 ==="
cd "$APP_DIR/frontend"
npm install
npm run build

echo "=== 重新啟動服務 ==="
sudo systemctl restart financial-radar
sudo systemctl reload nginx

echo "=== 部署完成 ==="
sudo systemctl status financial-radar --no-pager
