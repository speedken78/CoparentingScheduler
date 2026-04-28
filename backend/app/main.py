from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import admin, auth, cases, agent, schedules, handovers, reports, webhooks
from app.utils.errors import ErrorCode

app = FastAPI(title="Coparenting Scheduler API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(cases.router, prefix="/api/v1/cases", tags=["cases"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["agent"])
app.include_router(schedules.router, prefix="/api/v1")
app.include_router(handovers.router, prefix="/api/v1/handovers", tags=["handovers"])
app.include_router(reports.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # If detail is already our structured error dict, return as-is
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": ErrorCode.INTERNAL_ERROR, "message": str(exc.detail), "detail": None}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "Request validation failed",
                "detail": exc.errors(),
            }
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
