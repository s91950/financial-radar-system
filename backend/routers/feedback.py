"""Router for user feedback."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import Feedback, get_db

router = APIRouter()


class FeedbackCreate(BaseModel):
    category: str = "general"
    content: str


@router.post("/")
async def create_feedback(req: FeedbackCreate, db: Session = Depends(get_db)):
    """Submit user feedback."""
    fb = Feedback(category=req.category, content=req.content.strip())
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"id": fb.id, "message": "感謝您的回饋！"}


@router.get("/")
async def list_feedback(db: Session = Depends(get_db)):
    """List all feedback entries."""
    items = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return [
        {
            "id": f.id,
            "category": f.category,
            "content": f.content,
            "created_at": (f.created_at.isoformat() + "Z") if f.created_at else None,
        }
        for f in items
    ]


@router.delete("/{feedback_id}")
async def delete_feedback(feedback_id: int, db: Session = Depends(get_db)):
    """Delete a feedback entry."""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if fb:
        db.delete(fb)
        db.commit()
    return {"ok": True}
