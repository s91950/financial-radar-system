"""三模式認證 + 角色權限 dependency。

支援的認證方式（依優先順序）：
  1. Authorization: Bearer <jwt>         — 瀏覽器使用者登入後帶上
  2. X-API-Key: sk_xxx                    — Service API Key（Extension / scripts）
  3. X-API-Key: <legacy API_TOKEN>        — 過渡向後相容（角色視為 admin）
  4. 都沒帶                                 — 視為 "guest"

角色階層（數字越大權限越高）：
    guest(1) = regular(1) < admin(2) < owner(3)
    ※ 2026-05-09：guest 暫時放寬到與 regular 同級（看 ROLE_ORDER）。
       要回復原本 guest=0（看不到新聞 / 研究 / YT 等）把下面那行改回 0 即可。

使用方式：
    @router.get("/path", dependencies=[Depends(require_role("regular"))])
    def endpoint(): ...

    # 取得目前 user：
    @router.get("/me")
    def me(user: AuthContext = Depends(get_current_auth)):
        ...

向後相容：若 .env 設了舊 API_TOKEN 而沒設 JWT_SECRET，則 X-API-Key
帶這把舊 token 也會通過（角色自動視為 admin）。等所有 client 都換用
service key 後，可從 .env 移除 API_TOKEN。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.database import ServiceApiKey, User, get_db
from backend.security import (
    decode_access_token,
    looks_like_service_key,
    verify_service_key,
)

logger = logging.getLogger(__name__)

ROLE_ORDER = {"guest": 1, "regular": 1, "admin": 2, "owner": 3}  # guest 暫時=regular


@dataclass
class AuthContext:
    """請求的認證上下文。"""
    role: str                       # guest | regular | admin | owner
    user_id: Optional[int] = None   # 登入使用者 / None=guest 或 service key
    username: Optional[str] = None
    auth_kind: str = "guest"        # guest | jwt | service_key | legacy_token
    service_key_id: Optional[int] = None

    @property
    def is_authenticated(self) -> bool:
        return self.role != "guest"

    def has_role(self, min_role: str) -> bool:
        return ROLE_ORDER.get(self.role, 0) >= ROLE_ORDER.get(min_role, 0)


def _try_jwt(authorization: Optional[str]) -> Optional[AuthContext]:
    """嘗試解 Authorization: Bearer <jwt>。

    過期 / 無效一律 return None（視為無認證），讓 endpoint 自己決定：
      - 只要 guest 可看的 → 仍然回 200
      - 需要登入的 → require_role 會回 401
    這樣 JWT 自然過期不會把整個 UI 鎖到登入頁，只有點到需登入功能才提示。
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return None  # 過期 / 簽章錯 / 格式錯都視同無認證
    role = payload.get("role", "regular")
    if role not in ROLE_ORDER:
        return None
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    return AuthContext(
        role=role,
        user_id=user_id,
        username=payload.get("username"),
        auth_kind="jwt",
    )


def _try_service_key(presented: Optional[str], db: Session) -> Optional[AuthContext]:
    if not presented or not looks_like_service_key(presented):
        return None
    # 只比對未撤銷且 prefix 相符的 keys（避免 N 次 bcrypt verify 在大表上慢）
    prefix = presented[:9]  # sk_xxxxxx
    candidates = db.query(ServiceApiKey).filter(
        ServiceApiKey.is_revoked == False,
        ServiceApiKey.key_prefix == prefix,
    ).all()
    for sk in candidates:
        if verify_service_key(presented, sk.key_hash):
            # 更新 last_used_at（best-effort，不阻塞）
            try:
                sk.last_used_at = datetime.utcnow()
                db.commit()
            except Exception:
                db.rollback()
            return AuthContext(
                role=sk.role if sk.role in ROLE_ORDER else "regular",
                username=f"service:{sk.name}",
                auth_kind="service_key",
                service_key_id=sk.id,
            )
    return None


def _try_legacy_token(presented: Optional[str]) -> Optional[AuthContext]:
    """向後相容：舊的 API_TOKEN 直接視為 admin（過渡期用）。"""
    if not presented or looks_like_service_key(presented):
        return None
    expected = os.getenv("API_TOKEN", "").strip()
    if not expected:
        return None
    import hmac
    if hmac.compare_digest(presented, expected):
        return AuthContext(
            role="admin",
            username="legacy_token",
            auth_kind="legacy_token",
        )
    return None


def get_current_auth(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    """解析請求，回傳 AuthContext（永不丟 401，guest 也是合法狀態）。

    - Bearer JWT 解失敗 / 過期 → 401（避免 guest 偷塞壞 token）
    - 其他都沒帶 → guest
    """
    # 1. JWT
    ctx = _try_jwt(authorization)
    if ctx:
        request.state.auth = ctx
        return ctx

    # 2. Service key
    ctx = _try_service_key(x_api_key, db)
    if ctx:
        request.state.auth = ctx
        return ctx

    # 3. Legacy API_TOKEN（過渡期）
    ctx = _try_legacy_token(x_api_key)
    if ctx:
        request.state.auth = ctx
        return ctx

    # 4. Guest
    ctx = AuthContext(role="guest")
    request.state.auth = ctx
    return ctx


def require_role(min_role: str):
    """Dependency factory。若 auth context 角色 < min_role 則 401/403。"""
    if min_role not in ROLE_ORDER:
        raise ValueError(f"unknown role: {min_role}")

    def _dep(ctx: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if ctx.has_role(min_role):
            return ctx
        # 未登入 → 401（提示要登入），已登入但角色不足 → 403
        if ctx.role == "guest":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: requires role >= {min_role}",
        )

    return _dep


# 預先建好常用的 dependency 實例（FastAPI 會 cache 同一個 callable）
require_regular = require_role("regular")
require_admin = require_role("admin")
require_owner = require_role("owner")


# ── 向後相容：保留舊 require_api_token 名稱，但改成可被新角色 dep 取代 ──
def require_api_token(x_api_key: str = Header(default="")) -> None:
    """[Deprecated] 舊版單一 token 驗證，保留是為了不破壞還沒換掉的 endpoint。

    新程式碼請改用 require_role("...")。
    """
    expected = os.getenv("API_TOKEN", "").strip()
    if not expected:
        return
    import hmac
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
