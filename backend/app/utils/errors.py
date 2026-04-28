class ErrorCode:
    # Auth
    UNAUTHORIZED = "UNAUTHORIZED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    FORBIDDEN = "FORBIDDEN"

    # Case
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    CASE_ALREADY_MEMBER = "CASE_ALREADY_MEMBER"

    # Child
    CHILD_NOT_FOUND = "CHILD_NOT_FOUND"

    # General
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def error_response(code: str, message: str, detail=None) -> dict:
    return {"error": {"code": code, "message": message, "detail": detail}}


class AgentLoopError(Exception):
    """Agent 狀態機異常（超過 max iterations 或非預期 stop_reason）"""


class UnknownToolError(Exception):
    """Dispatcher 收到未定義的 tool name"""
