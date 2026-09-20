import sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.schema import Base, User, Favorite, Source, Event
from app.auth import hash_password, verify_password
from app.main import auto_migrate_db, engine, SessionLocal

def test_logical_withdrawal():
    auto_migrate_db()
    db = SessionLocal()
    try:
        # 1. Clean previous test user if exists
        test_username = "test_withdraw_user"
        old = db.query(User).filter(User.username == test_username).first()
        if old:
            db.delete(old)
            db.commit()

        # 2. Create test user
        user = User(
            username=test_username,
            email="test_withdraw@test.com",
            hashed_password=hash_password("testpass123"),
            is_paid=True,
            is_admin=False,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created user: id={user.id}, is_active={user.is_active}, withdrawn_at={user.withdrawn_at}")
        assert user.is_active is True
        assert user.withdrawn_at is None

        # Add a dummy favorite
        source = db.query(Source).first()
        if source:
            fav = Favorite(user_id=user.id, source_id=source.id)
            db.add(fav)
            db.commit()
            print(f"Added favorite for user. Count={len(user.favorites)}")

        # 3. Simulate withdrawal
        user.is_active = False
        user.withdrawn_at = datetime.utcnow()
        db.query(Favorite).filter(Favorite.user_id == user.id).delete()
        db.commit()
        db.refresh(user)

        print(f"After withdrawal: is_active={user.is_active}, withdrawn_at={user.withdrawn_at}, favs={len(user.favorites)}")
        assert user.is_active is False
        assert user.withdrawn_at is not None
        assert len(user.favorites) == 0

        # 4. Check query of active vs withdrawn
        active_users = db.query(User).filter(User.is_active != False).all()
        withdrawn_users = db.query(User).filter(User.is_active == False).all()
        print(f"Active users count: {len(active_users)}, Withdrawn users count: {len(withdrawn_users)}")
        assert any(u.username == test_username for u in withdrawn_users)
        assert not any(u.username == test_username for u in active_users)

        print("Test PASSED successfully!")
    finally:
        db.close()

if __name__ == "__main__":
    test_logical_withdrawal()
