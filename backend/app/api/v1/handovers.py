from fastapi import APIRouter

router = APIRouter()


@router.post("")
async def create_handover():
    # Milestone 2.3 實作
    return {"detail": "not implemented"}
