"""User repository (SDD Section 8.3: users)."""

import uuid

from sqlalchemy.orm import Session

from app.database.models import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)
