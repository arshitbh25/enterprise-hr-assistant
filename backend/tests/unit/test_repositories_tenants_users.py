"""Unit tests for TenantRepository and UserRepository."""

import uuid

from sqlalchemy.orm import Session

from app.database.repositories.tenants import TenantRepository
from app.database.repositories.users import UserRepository


def test_tenant_repository_get_returns_seeded_tenant(db: Session, seeded):
    tenant_id, _ = seeded
    tenant = TenantRepository(db).get(tenant_id)
    assert tenant is not None
    assert tenant.id == tenant_id


def test_tenant_repository_get_returns_none_for_unknown_id(db: Session, seeded):
    assert TenantRepository(db).get(uuid.uuid4()) is None


def test_user_repository_get_returns_seeded_user(db: Session, seeded):
    _, user_id = seeded
    user = UserRepository(db).get(user_id)
    assert user is not None
    assert user.id == user_id


def test_user_repository_get_returns_none_for_unknown_id(db: Session, seeded):
    assert UserRepository(db).get(uuid.uuid4()) is None
