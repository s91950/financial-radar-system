"""/api/users — owner-only 使用者管理。

- GET    /api/users           列出所有使用者
- POST   /api/users           建立新帳號
- PUT    /api/users/{id}      改 role / is_active
- POST   /api/users/{id}/reset-password   重設此人密碼，下次登入需改
- DELETE /api/users/{id}      刪除（不能刪自己 / 不能刪最後一個 owner）
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import AuthContext, ROLE_ORDER, require_owner
from backend.database import User, get_db
from backend.security import hash_password

router = APIRouter()


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "is_active": u.is_active,
        "must_change_password": u.must_change_password,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)
    role: str = Field(default="regular")


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


@router.get("")
def list_users(_: AuthContext = Depends(require_owner), db: Session = Depends(get_db)):
    return [_user_dict(u) for u in db.query(User).order_by(User.id).all()]


@router.post("")
def create_user(
    req: CreateUserRequest,
    _: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if req.role not in ROLE_ORDER or req.role == "guest":
        raise HTTPException(status_code=400, detail=f"非法 role：{req.role}")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="username 已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
        is_active=True,
        must_change_password=True,  # 第一次登入要改
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.put("/{user_id}")
def update_user(
    user_id: int,
    req: UpdateUserRequest,
    ctx: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")

    if req.role is not None:
        if req.role not in ROLE_ORDER or req.role == "guest":
            raise HTTPException(status_code=400, detail=f"非法 role：{req.role}")
        # 防呆：不能把最後一個 owner 降權
        if user.role == "owner" and req.role != "owner":
            owner_count = db.query(User).filter(User.role == "owner", User.is_active == True).count()
            if owner_count <= 1:
                raise HTTPException(status_code=400, detail="不能降權最後一個 owner")
        user.role = req.role

    if req.is_active is not None:
        # 防呆：不能停用最後一個 active owner
        if user.role == "owner" and not req.is_active:
            owner_count = db.query(User).filter(User.role == "owner", User.is_active == True).count()
            if owner_count <= 1:
                raise HTTPException(status_code=400, detail="不能停用最後一個 owner")
        user.is_active = req.is_active

    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    _: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    new_pw = "Tmp" + secrets.token_urlsafe(9)  # ~12 字暫時密碼，可讀
    user.password_hash = hash_password(new_pw)
    user.must_change_password = True
    db.commit()
    return {"username": user.username, "temporary_password": new_pw,
            "note": "請使用者用此密碼登入後立即修改"}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    ctx: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if ctx.user_id == user_id:
        raise HTTPException(status_code=400, detail="不能刪除自己")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    if user.role == "owner":
        owner_count = db.query(User).filter(User.role == "owner", User.is_active == True).count()
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="不能刪除最後一個 owner")
    db.delete(user)
    db.commit()
    return {"ok": True}
