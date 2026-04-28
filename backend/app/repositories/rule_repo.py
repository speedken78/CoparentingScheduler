from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.custody_rule import CustodyRule


class RuleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> CustodyRule:
        rule = CustodyRule(**data)
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def get_by_id(self, rule_id: UUID) -> CustodyRule | None:
        return await self.db.get(CustodyRule, rule_id)

    async def list_active(self, case_id: UUID) -> list[CustodyRule]:
        result = await self.db.execute(
            select(CustodyRule)
            .where(
                and_(
                    CustodyRule.case_id == case_id,
                    CustodyRule.revoked_at.is_(None),
                )
            )
            .order_by(CustodyRule.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke(
        self,
        rule_id: UUID,
        revoked_by: UUID,
        revoked_reason: str,
        revoked_at_date,
    ) -> CustodyRule | None:
        rule = await self.get_by_id(rule_id)
        if not rule or rule.revoked_at is not None:
            return None
        rule.revoked_at = datetime.now(timezone.utc)
        rule.revoked_by = revoked_by
        rule.revoked_reason = revoked_reason
        await self.db.flush()
        return rule
