# 貢獻指南 (Contributing Guide)

感謝你對 **金融即時偵測系統** 的興趣！

## 開發工作流

### 1. 複製與設定

```bash
git clone <repository-url> financial-radar
cd financial-radar
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### 2. 建立 Feature Branch

使用語義化分支命名:
```bash
git checkout -b feature/dashboard-heatmap
git checkout -b fix/alert-notification-bug
git checkout -b docs/improve-readme
git checkout -b chore/update-dependencies
```

**分支前綴**:
- `feature/` - 新功能
- `fix/` - 錯誤修復
- `docs/` - 文檔更新
- `chore/` - 依賴更新、配置變更
- `refactor/` - 代碼重構
- `test/` - 測試相關

### 3. 開發與提交

#### 提交消息格式

遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hant/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type 類型**:
- `feat` - 新功能
- `fix` - 錯誤修復
- `docs` - 文檔
- `style` - 代碼風格 (無業務邏輯變更)
- `refactor` - 重構
- `perf` - 性能改進
- `test` - 測試
- `chore` - 依賴更新、工具配置

**Scope 範圍**:
- `dashboard` - 儀表板
- `radar` - 即時雷達
- `search` - 主題搜尋
- `news` - 新聞資料庫
- `api` - API 層
- `frontend` - 前端
- `backend` - 後端

**範例**:
```bash
git commit -m "feat(dashboard): 新增市場熱力圖

- 實現 Recharts Heatmap 組件
- 集成後端 /api/dashboard/heat 端點
- 支援即時 WebSocket 推送更新

Closes #123"

git commit -m "fix(radar): 修復警報通知未推送的 bug

該修復解決警報完全沒有推送到 WebSocket 的問題。
根本原因是 _ws_manager 在 jobs.py 中未正確初始化。

Fixes #456"

git commit -m "docs: 更新 README 安裝指南"
```

### 4. 推送與建立 Pull Request

```bash
git push origin feature/dashboard-heatmap
```

在 GitHub/GitLab 中建立 PR，填寫以下內容:

```markdown
## 🎯 目標
簡述此 PR 要解決的問題或實現的功能。

## 📝 變更說明
- 實現 Recharts 熱力圖組件
- 新增 /api/dashboard/heat 後端端點
- 支援實時數據推送

## 🧪 測試方法
1. 啟動後端與前端
2. 導航至 /dashboard
3. 觀察熱力圖每 30s 自動更新

## ✅ 檢查清單
- [ ] 代碼遵循項目風格指南
- [ ] 新功能包含單元測試
- [ ] 文檔已更新
- [ ] 提交消息清晰且有意義
- [ ] 本地測試已驗證變更

## 📦 相關問題
Fixes #123
Related to #456
```

---

## 代碼風格指南

### Python (後端)

遵循 [PEP 8](https://pep8.org/):

```python
# 好的例子
async def analyze_alert(alert_id: int, db: Session = Depends(get_db)) -> dict:
    """Analyze an alert using Claude API.

    Args:
        alert_id: Alert database ID
        db: Database session dependency

    Returns:
        Dictionary containing analysis results

    Raises:
        ValueError: If alert not found
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise ValueError("Alert not found")

    analysis = await claude_ai.analyze_news(
        articles=[{"title": alert.title, "content": alert.content}]
    )
    return {"analysis": analysis}

# 避免
def analyze_alert(alert_id,db):
    """Analyze alert"""
    alert=db.query(Alert).filter(Alert.id==alert_id).first()
    if not alert: return {}
    return {"analysis": "..."}
```

**規則**:
- 使用 Type Hints
- 最多 88 字元一行 (使用 Black formatter)
- 函數/類別需要 docstring (Google 風格)
- 避免 Magic Numbers，使用常數
- 非同步函數使用 `async def`

### JavaScript/React (前端)

遵循 [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript):

```jsx
// 好的例子
export default function DashboardPage() {
  const [heatData, setHeatData] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadHeatData()
  }, [loadHeatData])

  const loadHeatData = useCallback(async () => {
    try {
      const { data } = await dashboardAPI.getHeat()
      setHeatData(data)
    } catch (err) {
      console.error('Failed to load heat data:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  if (loading) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">市場熱力</h1>
      <HeatmapChart data={heatData} />
    </div>
  )
}

// 避免
export default function Dashboard(){
  const[data,setData]=useState([])
  useEffect(()=>{dashboardAPI.getHeat().then(r=>setData(r.data))},)
  return <div><Heatmap data={data}/></div>
}
```

**規則**:
- 使用函數組件 + Hooks (無 Class)
- 明確的 Prop Types / TypeScript (如果使用)
- 最多 100 字元一行
- 使用有意義的變數名稱
- 避免 Inline 複雜邏輯

---

## 測試指南

### 後端測試

使用 `pytest`:

```bash
# 安裝測試依賴
pip install pytest pytest-asyncio pytest-cov

# 執行所有測試
pytest

# 執行特定測試
pytest tests/test_radar.py::test_analyze_alert

# 查看覆蓋率
pytest --cov=backend tests/
```

**測試結構**:
```python
# tests/test_radar.py
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_get_alerts_returns_list():
    """Test GET /api/radar/alerts returns alert list."""
    response = client.get("/api/radar/alerts?limit=10")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@pytest.mark.asyncio
async def test_analyze_alert_with_invalid_id():
    """Test analyze endpoint with non-existent alert."""
    response = client.post("/api/radar/alerts/99999/analyze")
    assert response.status_code == 404
```

### 前端測試

使用 `vitest` 或 `jest`:

```bash
# 執行測試
npm test

# 監視模式
npm test -- --watch

# 覆蓋率報告
npm test -- --coverage
```

---

## 文檔更新

新增功能時務必更新文檔:

1. **代碼註釋** - 解釋「為什麼」，不是「做什麼」
2. **Docstring** - Python 函數/類別必須有
3. **README.md** - 更新快速開始/配置部分
4. **API 文檔** - FastAPI 自動生成 (SwaggerUI @ `/docs`)
5. **CHANGELOG.md** - 記錄變更摘要
6. **ROADMAP.md** - 更新進度 (打勾完成項目)

---

## 本地開發環境設定

### 後端

```bash
# 建立虛擬環境
python -m venv venv

# 激活虛擬環境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安裝依賴
pip install -r backend/requirements.txt

# 啟動開發伺服器
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端

```bash
cd frontend

# 安裝依賴
npm install

# 開發伺服器 (Vite @ :5173)
npm run dev

# 建置生產版本
npm run build
```

---

## 常見開發任務

### 新增 API 端點

1. 在 `backend/routers/xxx.py` 中定義路由
2. 在 `backend/services/xxx.py` 中實現業務邏輯
3. 在 `frontend/src/services/api.js` 中新增 API 呼叫
4. 在對應前端頁面中使用

### 新增資料庫表格

1. 在 `backend/database.py` 中定義 SQLAlchemy 模型
2. 刪除 `data/financial_radar.db` (以重新種子化)
3. 重啟後端 (自動建立新表)
4. 更新相關路由和服務

### 修改通知格式

編輯 `backend/services/notification.py`:
- `format_alert_message()` - LINE/WebSocket 格式
- `format_alert_email()` - Email HTML 格式

---

## PR 審查清單

在提交 PR 前檢查:

- [ ] 代碼編譯無誤
- [ ] 本地測試通過
- [ ] 沒有 linting 警告
- [ ] 提交消息清晰且符合慣例
- [ ] 文檔已更新
- [ ] 沒有敏感訊息 (API 密鑰等)
- [ ] CHANGELOG.md 已更新
- [ ] PR 敘述包含測試方法

---

## 問題報告 (Issue)

發現 bug 或有功能請求？提交 Issue:

```markdown
## 🐛 Bug Report

**描述**:
簡述問題。

**複現步驟**:
1. 進入儀表板
2. 點擊「刷新」按鈕
3. 應用崩潰

**預期行為**:
應該顯示更新後的數據。

**實際行為**:
白屏，主控台顯示 `TypeError: Cannot read...`

**環境**:
- OS: Windows 10
- Browser: Chrome 120
- 分支: master

**附加信息**:
[錯誤截圖/日誌]
```

---

## 聯絡方式

- **Bug 報告**: GitHub Issues
- **功能請求**: Discussions 或 GitHub Issues
- **一般詢問**: Discussions

---

感謝你的貢獻！ 🙌

**最後更新**: 2026-03-23
