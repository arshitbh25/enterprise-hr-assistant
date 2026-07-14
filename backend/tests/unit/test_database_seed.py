"""Unit tests for app.database.seed."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.models import Tenant, User
from app.database.repositories.tenants import TenantRepository
from app.database.repositories.users import UserRepository
from app.database.seed import seed_defaults


def test_seed_defaults_creates_tenant_and_user(db: Session, test_settings: Settings):
    seed_defaults(db, test_settings)

    tenant = TenantRepository(db).get(uuid.UUID(test_settings.default_tenant_id))
    user = UserRepository(db).get(uuid.UUID(test_settings.default_user_id))

    assert tenant is not None
    assert tenant.name == test_settings.default_tenant_name
    assert user is not None
    assert user.email == test_settings.default_user_email
    assert user.tenant_id == tenant.id


def test_seed_defaults_is_idempotent(db: Session, test_settings: Settings):
    seed_defaults(db, test_settings)
    seed_defaults(db, test_settings)  # must not raise or duplicate

    tenant_count = db.scalar(select(func.count()).select_from(Tenant))
    user_count = db.scalar(select(func.count()).select_from(User))

    assert tenant_count == 1
    assert user_count == 1
