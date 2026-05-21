# app/agents/dispatcher.py
import json
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentContext
from app.agents.tools.definitions import KNOWN_TOOL_NAMES
from app.services import schedule_service
from app.utils.errors import UnknownToolError


async def dispatch_tool(
    tool_name: str,
    tool_input: dict,
    ctx: AgentContext,
    db: AsyncSession,
) -> dict:
    """
    把 LLM 的 tool_use 轉成後端 service 呼叫。
    永遠回傳 dict（作為 tool_result content）。
    """
    if tool_name not in KNOWN_TOOL_NAMES:
        raise UnknownToolError(f"Unknown tool: {tool_name}")

    # --- ask_clarification ---
    # 不需後端動作，把問題結構原樣回傳，讓 LLM 繼續生成給使用者看的文字
    if tool_name == "ask_clarification":
        return {
            "status": "awaiting_user_reply",
            "payload": tool_input,
        }

    # --- detect_conflict_before_write ---
    if tool_name == "detect_conflict_before_write":
        conflicts = await schedule_service.detect_conflicts(ctx, tool_input, db)
        return {
            "conflicts": conflicts,
            "has_conflict": len(conflicts) > 0,
        }

    # --- create_recurring_custody_rule ---
    if tool_name == "create_recurring_custody_rule":
        # confidence 低於 0.8 不應走到這裡（LLM 應先 ask_clarification）
        # 但 dispatcher 加一道防護
        if tool_input.get("confidence", 1.0) < 0.8:
            return {
                "status": "rejected",
                "reason": "confidence_too_low",
                "message": "請先確認解析結果再建立規則",
            }
        rule = await schedule_service.create_rule(ctx, tool_input, db)
        return {
            "status": "created",
            "rule_id": str(rule["id"]),
            "summary": rule["summary"],
        }

    # --- create_one_time_event ---
    if tool_name == "create_one_time_event":
        if tool_input.get("confidence", 1.0) < 0.8:
            return {"status": "rejected", "reason": "confidence_too_low"}
        event = await schedule_service.create_event(ctx, tool_input, db)
        return {
            "status": "created",
            "event_id": str(event["id"]),
            "summary": event["summary"],
        }

    # --- propose_rule_revocation ---
    if tool_name == "propose_rule_revocation":
        proposal = await schedule_service.propose_revocation(ctx, tool_input, db)
        return {
            "status": "awaiting_user_confirmation",
            "proposal_id": str(proposal["id"]),
            "message": "已建立撤銷提案，請在確認頁面審核",
        }

    # --- delete_custody_event ---
    if tool_name == "delete_custody_event":
        return await schedule_service.delete_event(ctx, tool_input, db)

    # --- summarize_and_confirm ---
    if tool_name == "summarize_and_confirm":
        return {"status": "acknowledged"}

    raise UnknownToolError(tool_name)
