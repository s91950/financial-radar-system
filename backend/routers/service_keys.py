"""/api/service-keys — owner-only Service API Keys 管理。

- GET    /api/service-keys           列出所有 keys（含已撤銷的）
- POST   /api/service-keys           建立新 key（**回傳的 full_key 僅此一次顯示**）
- DELETE /api/service-keys/{id}      撤銷（軟刪：is_revoked=True）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import AuthContext, ROLE_ORDER, require_owner
from backend.database import ServiceApiKey, get_db
from backend.security import generate_service_key

router = APIRouter()


def _key_dict(k: ServiceApiKey, full_key: str | None = None) -> dict:
    out = {
        "id": k.id,
        "name": k.name,
        "key_prefix": k.key_prefix,
        "role": k.role,
        "is_revoked": k.is_revoked,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_by_user_id": k.created_by_user_id,
    }
    if full_key is not None:
        out["full_key"] = full_key
        out["_warning"] = "此完整 key 只在建立當下回傳一次；請立即儲存，無法再次取得"
    return out


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    role: str = Field(default="admin")  # 通常是 admin（讓 Extension/scripts 能寫報告）


@router.get("")
def list_keys(_: AuthContext = Depends(require_owner), db: Session = Depends(get_db)):
    rows = db.query(ServiceApiKey).order_by(ServiceApiKey.id.desc()).all()
    return [_key_dict(k) for k in rows]


@router.post("")
def create_key(
    req: CreateKeyRequest,
    ctx: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if req.role not in ROLE_ORDER or req.role in ("guest", "owner"):
        raise HTTPException(
            status_code=400,
            detail=f"非法 role：{req.role}（service key 不能是 guest 或 owner）",
        )
    full_key, prefix, key_hash = generate_service_key()
    k = ServiceApiKey(
        name=req.name,
        key_prefix=prefix,
        key_hash=key_hash,
        role=req.role,
        created_by_user_id=ctx.user_id,
        is_revoked=False,
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    return _key_dict(k, full_key=full_key)


@router.delete("/{key_id}")
def revoke_key(
    key_id: int,
    _: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    k = db.query(ServiceApiKey).filter(ServiceApiKey.id == key_id).first()
    if not k:
        raise HTTPException(status_code=404, detail="key 不存在")
    if k.is_revoked:
        return {"ok": True, "already_revoked": True}
    k.is_revoked = True
    db.commit()
    return {"ok": True}
