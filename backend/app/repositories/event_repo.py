from uuid import UUID
from datetime import datetime, timezone as dt_tz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update
from app.models.custody_event import CustodyEvent


class EventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def bulk_insert(self, events_data: list[dict]) -> list[CustodyEvent]:
        """一次插入多個事件。若 exclusion constraint 擋下，由呼叫方用 savepoint 隔離。"""
        events = [CustodyEvent(**d) for d in events_data]
        self.db.add_all(events)
        await self.db.flush()
        return events

    async def list_in_range(
        self,
        case_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[CustodyEvent]:
        result = await self.db.execute(
            select(CustodyEvent)
            .where(
                and_(
                    CustodyEvent.case_id == case_id,
                    CustodyEvent.deleted_at.is_(None),
                    CustodyEvent.starts_at < end,
                    CustodyEvent.ends_at > start,
                )
            )
            .order_by(CustodyEvent.starts_at.asc())
        )
        return list(result.scalars().all())

    async def list_by_rule_id(self, rule_id: UUID) -> list[CustodyEvent]:
        result = await self.db.execute(
            select(CustodyEvent)
            .where(
                and_(
                    CustodyEvent.rule_id == rule_id,
                    CustodyEvent.deleted_at.is_(None),
                    CustodyEvent.status == "scheduled",
                )
            )
            .order_by(CustodyEvent.starts_at.asc())
        )
        return list(result.scalars().all())

    async def list_scheduled_after(
        self,
        rule_id: UUID,
        after: datetime,
    ) -> list[CustodyEvent]:
        result = await self.db.execute(
            select(CustodyEvent)
            .where(
                and_(
                    CustodyEvent.rule_id == rule_id,
                    CustodyEvent.starts_at >= after,
                    CustodyEvent.status == "scheduled",
                    CustodyEvent.deleted_at.is_(None),
                )
            )
            .order_by(CustodyEvent.starts_at.asc())
        )
        return list(result.scalars().all())

    async def soft_delete(self, event_id: UUID, case_id: UUID) -> CustodyEvent | None:
        event = await self.db.get(CustodyEvent, event_id)
        if not event or str(event.case_id) != str(case_id) or event.deleted_at:
            return None
        event.deleted_at = datetime.now(dt_tz.utc)
        await self.db.flush()
        return event

    async def delete_scheduled_by_rule_after(
        self,
        rule_id: UUID,
        after: datetime,
    ) -> int:
        """軟刪除某規則展開的、在指定時間之後、狀態為 scheduled 的事件。回傳刪除筆數。"""
        result = await self.db.execute(
            update(CustodyEvent)
            .where(
                and_(
                    CustodyEvent.rule_id == rule_id,
                    CustodyEvent.starts_at >= after,
                    CustodyEvent.status == "scheduled",
                    CustodyEvent.deleted_at.is_(None),
                )
            )
            .values(deleted_at=datetime.now(dt_tz.utc))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount
