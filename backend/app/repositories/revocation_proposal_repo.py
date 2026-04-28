from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.revocation_proposal import RevocationProposal


class RevocationProposalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> RevocationProposal:
        p = RevocationProposal(**data)
        self.db.add(p)
        await self.db.flush()
        return p

    async def get_by_id(self, proposal_id: UUID) -> RevocationProposal | None:
        return await self.db.get(RevocationProposal, proposal_id)

    async def list_pending(self, case_id: UUID) -> list[RevocationProposal]:
        result = await self.db.execute(
            select(RevocationProposal)
            .where(
                RevocationProposal.case_id == case_id,
                RevocationProposal.status == "pending",
            )
            .order_by(RevocationProposal.created_at.desc())
        )
        return list(result.scalars().all())
