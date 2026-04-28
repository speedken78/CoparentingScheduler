from fastapi import APIRouter

router = APIRouter()


@router.post("/gcal")
async def gcal_webhook():
    # Milestone 1.5 實作
    return {"detail": "not implemented"}


@router.post("/line")
async def line_webhook():
    # Milestone 2.2 實作
    return {"detail": "not implemented"}
