"""bcrypt 密碼雜湊 + JWT 簽發/驗證的純函式 helpers。

不直接做認證流程（那在 auth.py），這裡只負責：
- hash_password / verify_password — bcrypt 包薄薄一層
- create_access_token / decode_access_token — JWT HS256
- generate_service_key / hash_service_key / verify_service_key — service key 用同樣 bcrypt
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

# JWT 設定
JWT_ALG = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))


def _jwt_secret() -> str:
    """讀取 JWT_SECRET。若沒設則 fallback 用 API_TOKEN（向後相容過渡用）。"""
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        secret = os.getenv("API_TOKEN", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET 未設定（也沒 fallback API_TOKEN），無法簽發 token")
    return secret


# ── Password hashing ──────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """bcrypt hash。回傳字串（含 salt + cost factor）。"""
    if not plain:
        raise ValueError("password 不能為空")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """timing-safe verify。"""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ────────────────────────────────────────────────────────────────

def create_access_token(*, user_id: int, username: str, role: str,
                        expires_hours: Optional[int] = None) -> str:
    now = datetime.now(timezone.utc)
    exp_hours = expires_hours if expires_hours is not None else JWT_EXPIRE_HOURS
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=exp_hours)).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict:
    """解 JWT。token 過期或簽章失敗會 raise jwt.PyJWTError（caller 處理）。"""
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALG])


# ── Service API Keys ──────────────────────────────────────────────────

# Key 格式：固定 prefix `sk_` + URL-safe 32 字元，總長 ~46
# prefix 用來辨識「這是 service key 不是 JWT」並可截前 8 字當顯示用
SERVICE_KEY_PREFIX = "sk_"


def generate_service_key() -> tuple[str, str, str]:
    """產生新的 service key。回傳 (full_key, key_prefix_for_display, key_hash)。

    full_key 只在「建立的當下」回給 owner 看一次，DB 只存 hash。
    """
    raw = secrets.token_urlsafe(32)
    full = f"{SERVICE_KEY_PREFIX}{raw}"
    key_hash = bcrypt.hashpw(full.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")
    # 顯示用：取前 8 字元（含 sk_）讓使用者能辨識，這部分不機密
    display_prefix = full[: len(SERVICE_KEY_PREFIX) + 6]  # e.g. sk_AbCdEf
    return full, display_prefix, key_hash


def verify_service_key(presented: str, stored_hash: str) -> bool:
    if not presented or not stored_hash:
        return False
    try:
        return bcrypt.checkpw(presented.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False


def looks_like_service_key(s: str) -> bool:
    return bool(s) and s.startswith(SERVICE_KEY_PREFIX)
