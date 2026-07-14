"""Idempotent startup seed: default tenant + user (ADR-007, single-tenant v1).

Real tenant/user onboarding is a Phase-12 (SaaS hardening) concern; v1
needs exactly one valid tenant/user pair for the auth stub and stub
endpoints to reference as foreign keys.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import TenantStatus, UserRole
from app.database.models import Tenant, User


def seed_defaults(db: Session, settings: Settings) -> None:
    tenant_id = uuid.UUID(settings.default_tenant_id)
    user_id = uuid.UUID(settings.default_user_id)

    if db.get(Tenant, tenant_id) is None:
        db.add(Tenant(id=tenant_id, name=settings.default_tenant_name, status=TenantStatus.ACTIVE))

    if db.get(User, user_id) is None:
        db.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=settings.default_user_email,
                display_name=settings.default_user_display_name,
                role=UserRole.HR_ADMIN,
            )
        )

    db.commit()
