import hashlib
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.schema import User

def hash_password(password: str) -> str:
    """SHA-256を用いた安定したパスワードハッシュ化"""
    salt = "ojuken_search_salt_2026"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password

def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User:
    username = request.cookies.get("current_user")
    if not username:
        return None
    user = db.query(User).filter(User.username == username).first()
    if not user or getattr(user, "is_active", True) is False:
        return None
    return user

def get_current_user_required(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="ログインが必要です"
        )
    return user
