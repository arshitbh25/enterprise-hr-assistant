"""Tenant repository (SDD Section 8.3: tenants)."""

import uuid

from sqlalchemy.orm import Session

from app.database.models import Tenant


class TenantRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return self.db.get(Tenant, tenant_id)
