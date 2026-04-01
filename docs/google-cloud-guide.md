# Google Cloud 使用指南

## 基本資訊

| 項目 | 內容 |
|------|------|
| 服務商 | Google Cloud Platform |
| 機型 | e2-micro（2 vCPU, 1GB RAM） |
| 地區 | us-east1-d（美國東部） |
| OS | Ubuntu 22.04 LTS |
| 公開 IP | 34.23.154.194 |
| 費用 | 永久免費（Always Free 方案） |

## 免費額度說明

以下項目在 us-east1 地區永久免費，不會收費：
- **e2-micro VM**：1 台，每月免費
- **30GB 標準永久磁碟**：每月免費
- **1GB 網路流量**：每月免費（出站至北美）

> ⚠️ **確認不收費的方法**：
> Google Cloud Console → 左側選單 → **帳單** → **預算與快訊**
> → 建立預算，設定金額 $1，有任何費用立即 Email 通知

---

## 日常維護指令

### SSH 連線
Google Cloud Console → Compute Engine → VM 執行個體 → 點 **SSH** 按鈕

### 服務管理
```bash
# 查看服務狀態
sudo systemctl status financial-radar

# 重啟服務
sudo systemctl restart financial-radar

# 查看即時日誌（Ctrl+C 退出）
sudo journalctl -u financial-radar -f

# 查看最近 50 行日誌
sudo journalctl -u financial-radar -n 50 --no-pager
```

### 系統資源
```bash
# 磁碟使用量（確認未超過 30GB）
df -h

# 記憶體使用量
free -h

# CPU 使用率
top
```

---

## 更新程式碼

每次在本機修改程式後：

**1. 本機推送到 GitHub**
```bash
git add .
git commit -m "更新說明"
git push
```

**2. SSH 進 VM 拉取更新**
```bash
cd /opt/financial-radar && git pull
sudo systemctl restart financial-radar
```

**若有前端改動（.jsx/.js/.css）需額外執行：**
```bash
cd /opt/financial-radar/frontend && npm run build
sudo systemctl restart financial-radar
```

---

## 資料庫管理

資料庫位置：`/opt/financial-radar/data/financial_radar.db`

```bash
# 備份資料庫
sqlite3 /opt/financial-radar/data/financial_radar.db .dump > ~/backup_$(date +%Y%m%d).sql

# 查看資料庫大小
du -sh /opt/financial-radar/data/

# 查看資料表
sqlite3 /opt/financial-radar/data/financial_radar.db ".tables"
```

---

## 容量監控

```bash
# 磁碟使用量明細
du -sh /opt/financial-radar/*

# 日誌佔用空間
sudo journalctl --disk-usage
```

若日誌過大可清理：
```bash
sudo journalctl --vacuum-size=100M
```

---

## 緊急處理

**服務掛掉無法啟動：**
```bash
sudo journalctl -u financial-radar -n 100 --no-pager
# 查看錯誤原因後重啟
sudo systemctl restart financial-radar
```

**VM 無回應：**
Google Cloud Console → Compute Engine → 點 VM → **重設**（強制重開機）
服務設有 systemd 自動啟動，重開機後會自動恢復。
