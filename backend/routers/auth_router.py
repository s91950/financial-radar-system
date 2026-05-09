"""/api/auth — 登入、登出、me、改密碼。

- POST /api/auth/login          — 任何人可呼叫
- GET  /api/auth/me             — 已登入即可
- POST /api/auth/change-password — 已登入即可，需提供舊密碼
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import AuthContext, get_current_auth, require_regular
from backend.database import User, get_db
from backend.security import (
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    user: dict


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username, User.is_active == True).first()
    if not user or not verify_password(req.password, user.password_hash):
        # 統一錯誤訊息避免 username enumeration
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    user.last_login_at = datetime.utcnow()
    db.commit()
    token = create_access_token(user_id=user.id, username=user.username, role=user.role)
    return LoginResponse(
        access_token=token,
        user={
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "must_change_password": user.must_change_password,
        },
    )


@router.get("/me")
def me(ctx: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    """回傳目前認證上下文。未登入也回（role=guest）。"""
    if ctx.role == "guest":
        return {"role": "guest", "authenticated": False}
    base = {
        "role": ctx.role,
        "username": ctx.username,
        "auth_kind": ctx.auth_kind,
        "authenticated": True,
    }
    if ctx.user_id:
        u = db.query(User).filter(User.id == ctx.user_id).first()
        if u:
            base["id"] = u.id
            base["must_change_password"] = u.must_change_password
            base["created_at"] = u.created_at.isoformat() if u.created_at else None
            base["last_login_at"] = u.last_login_at.isoformat() if u.last_login_at else None
    return base


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    ctx: AuthContext = Depends(require_regular),
    db: Session = Depends(get_db),
):
    if ctx.auth_kind != "jwt" or not ctx.user_id:
        raise HTTPException(status_code=403, detail="只能用使用者帳號（JWT）改密碼")
    user = db.query(User).filter(User.id == ctx.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="目前密碼錯誤")
    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    db.commit()
    return {"ok": True}
