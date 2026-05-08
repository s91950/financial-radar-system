"""API Token 驗證（opt-in 設計）。

設計目標：在不破壞任何現行行為的前提下加上可選的 API token 保護。
- 若 VM .env 沒設定 `API_TOKEN`：依賴函式直接放行，等同沒有驗證
- 若有設定：所有套用此 dependency 的 router 都必須帶 `X-API-Key` header

啟用方式：
  1. 在 VM `.env` 加入 `API_TOKEN=<隨機長字串>`
     可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 產生
  2. 各端 client（前端 / Extension / scripts）都更新後再 restart 服務生效
  3. LINE webhook 路徑用自己的 HMAC 簽章驗證，不掛此 dependency
"""
import hmac
import os

from fastapi import Header, HTTPException, status


def require_api_token(x_api_key: str = Header(default="")) -> None:
    """FastAPI Dependency：驗證 X-API-Key header。

    - `API_TOKEN` env 未設定 → 不驗（向後相容）
    - 已設定但 header 不符 → 401
    """
    expected = os.getenv("API_TOKEN", "")
    if not expected:
        return
    # hmac.compare_digest 防 timing attack
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
