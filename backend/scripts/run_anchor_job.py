#!/usr/bin/env python3
"""
本地手動觸發稽核錨定。
用法：docker compose exec api python scripts/run_anchor_job.py
"""
import asyncio
import sys
import os

sys.path.insert(0, "/app")
os.environ.setdefault("ENV", "development")

from app.database import AsyncSessionLocal
from app.services.audit_anchor_service import run_anchor_job


async def main():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await run_anchor_job(db)
    print(f"Anchor result: {result}")
    if result["status"] == "anchored":
        print(f"✓ Anchored audit_log #{result['last_audit_id']}")
        print(f"  Hash: {result['last_row_hash'][:16]}...")
        print(f"  Proof: {result['anchor_proof']}")
    elif result["status"] == "skipped":
        print(f"- Skipped: {result.get('reason', '')}")
    else:
        print(f"✗ Failed: {result.get('error', '')}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
