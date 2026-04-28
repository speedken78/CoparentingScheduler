# app/services/agent_service.py
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.agents.context import AgentContext, load_context
from app.agents.tools.definitions import get_tools_with_cache
from app.agents.prompts.scheduler_v1 import build_system_prompt, PROMPT_VERSION
from app.agents.dispatcher import dispatch_tool
from app.models.agent_session import AgentSession, AgentMessage
from app.services.audit_service import log as audit_log
from app.utils.errors import AgentLoopError, UnknownToolError

MAX_ITERATIONS = 6

client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


async def get_or_create_session(
    case_id: UUID,
    user_id: UUID,
    session_id: UUID | None,
    db: AsyncSession,
) -> UUID:
    """
    若 session_id 為 None，建立新 session 並回傳新 id。
    若有 session_id，驗證它屬於此 user/case，回傳原 id。
    """
    if session_id is None:
        new_session = AgentSession(
            id=uuid4(),
            case_id=case_id,
            user_id=user_id,
        )
        db.add(new_session)
        await db.flush()
        return new_session.id

    # 驗證既有 session 的歸屬
    session = await db.get(AgentSession, session_id)
    if not session or str(session.case_id) != str(case_id) or \
       str(session.user_id) != str(user_id):
        raise ValueError("Invalid session_id")
    return session_id


async def persist_message(
    db: AsyncSession,
    session_id: UUID,
    role: str,
    content,                          # str 或 list（Anthropic 格式）
    tool_use_id: str | None = None,
    tool_name: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """把每一輪的訊息存進 agent_messages。"""
    msg = AgentMessage(
        id=uuid4(),
        session_id=session_id,
        role=role,
        content=content if isinstance(content, (dict, list)) else {"text": content},
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(msg)
    await db.flush()


def extract_user_facing_text(response) -> str:
    """從 Anthropic response 取出給使用者看的文字。"""
    texts = []
    for block in response.content:
        if block.type == "text":
            texts.append(block.text)
    return "\n".join(texts) if texts else "（已完成）"


async def handle_message(
    case_id: UUID,
    user_id: UUID,
    user_text: str,
    session_id: UUID | None,
    db: AsyncSession,
    ip_address: str | None = None,
    user_agent: str | None = None,
    user=None,
) -> dict:
    """
    主入口。處理一則使用者訊息，執行 LLM 狀態機，回傳結果。

    回傳格式：
    {
        "session_id": "uuid",
        "reply": "AI 回覆的中文文字",
        "actions_taken": [{"tool": "...", "result": {...}}, ...],
        "requires_clarification": bool,
        "clarification_options": [...]  # 若 requires_clarification=True
    }
    """
    async with db.begin_nested():  # savepoint，讓外層 transaction 控制 commit
        # 1. 取得或建立 session
        sid = await get_or_create_session(case_id, user_id, session_id, db)

        # 2. 載入 context（歷史訊息 + 現有規則）
        ctx = await load_context(sid, case_id, user_id, db)

        # 3. 新增使用者訊息到 context 與 DB
        ctx.append_user_message(user_text)
        await persist_message(db, sid, "user", user_text)

        # 4. 寫 audit_log（記錄使用者的原始輸入）
        await audit_log(
            db,
            case_id=case_id,
            actor_id=user_id,
            action="agent_user_input",
            entity_type="agent_session",
            entity_id=sid,
            after_state={"text": user_text},
            triggered_by="human",
            agent_session_id=sid,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # 5. 狀態機主迴圈
        actions_taken = []
        clarification_payload = None
        reply = "（已完成）"

        for iteration in range(MAX_ITERATIONS):
            resp = await client.messages.create(
                model=settings.ANTHROPIC_MODEL,   # "claude-haiku-4-5"
                max_tokens=2048,
                temperature=0,
                system=build_system_prompt(
                    today_date=ctx.today_label(),
                    case_timezone=ctx.case_timezone,
                    active_rules=ctx.active_rules,
                ),
                tools=get_tools_with_cache(),
                messages=ctx.truncated_messages(),
            )

            # 持久化 assistant 訊息（含 token 用量）
            await persist_message(
                db, sid, "assistant",
                content=[b.model_dump() for b in resp.content],
                model=resp.model,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            )

            # 更新 context
            ctx.append_assistant_response([b.model_dump() for b in resp.content])

            # --- 判斷 stop_reason ---
            if resp.stop_reason == "end_turn":
                reply = extract_user_facing_text(resp)
                break

            if resp.stop_reason == "tool_use":
                tool_results = []

                for block in resp.content:
                    if block.type != "tool_use":
                        continue

                    # 寫 audit_log：Agent 呼叫了哪個 tool
                    await audit_log(
                        db,
                        case_id=case_id,
                        actor_id=user_id,
                        action="agent_tool_call",
                        entity_type="agent_session",
                        entity_id=sid,
                        after_state={
                            "tool": block.name,
                            "input": block.input,
                            "reasoning": block.input.get("reasoning", ""),
                        },
                        triggered_by="agent",
                        agent_session_id=sid,
                    )

                    # dispatch
                    result = await dispatch_tool(
                        tool_name=block.name,
                        tool_input=block.input,
                        ctx=ctx,
                        db=db,
                    )

                    # 特殊處理 ask_clarification
                    if block.name == "ask_clarification":
                        clarification_payload = result

                    # 特殊處理 summarize_and_confirm 觸發稽核
                    if block.name == "summarize_and_confirm":
                        await audit_log(
                            db,
                            case_id=case_id,
                            actor_id=user_id,
                            action="agent_session_summarized",
                            entity_type="agent_session",
                            entity_id=sid,
                            after_state={"summary": block.input.get("summary", "")},
                            triggered_by="agent",
                            agent_session_id=sid,
                        )

                    actions_taken.append({
                        "tool": block.name,
                        "input": block.input,
                        "result": result,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                # 把 tool_results 餵回 context
                ctx.append_tool_results(tool_results)
                await persist_message(db, sid, "tool_result", tool_results)
                continue  # 繼續迴圈，再呼叫一次 LLM

            # 其他 stop_reason（max_tokens 等）
            raise AgentLoopError(f"Unexpected stop_reason: {resp.stop_reason}")

        else:
            # 超過 MAX_ITERATIONS
            raise AgentLoopError("Exceeded max iterations without end_turn")

        # 6. 更新 session 的 last_active_at
        session = await db.get(AgentSession, sid)
        if session:
            session.last_active_at = datetime.now(timezone.utc)

    # GCal 同步在 savepoint release 後、transaction commit 前觸發
    for action in actions_taken:
        if action["tool"] in ("create_recurring_custody_rule", "create_one_time_event"):
            if "id" in action["result"]:
                await _trigger_gcal_sync_after_create(action, user, user_id, db)

    return {
        "session_id": str(sid),
        "reply": reply,
        "actions_taken": actions_taken,
        "requires_clarification": clarification_payload is not None,
        "clarification_options": (
            clarification_payload.get("payload", {}).get("options", [])
            if clarification_payload else []
        ),
    }


async def _trigger_gcal_sync_after_create(
    action: dict,
    user,
    user_id: UUID,
    db: AsyncSession,
) -> None:
    """建立規則或事件後，把展開的 custody_events 同步到 GCal。失敗不拋錯。"""
    import logging
    from app.services.gcal_sync_service import sync_events_batch
    from app.repositories.event_repo import EventRepository

    try:
        # 若 user 未傳入，從 DB 取
        if user is None:
            from app.models.user import User as UserModel
            user = await db.get(UserModel, user_id)
        if user is None:
            return

        if action["tool"] == "create_recurring_custody_rule":
            rule_id = action["result"].get("id")
            if not rule_id:
                return
            events = await EventRepository(db).list_by_rule_id(rule_id)

        elif action["tool"] == "create_one_time_event":
            event_id = action["result"].get("id")
            if not event_id:
                return
            from app.models.custody_event import CustodyEvent
            event = await db.get(CustodyEvent, event_id)
            events = [event] if event else []

        else:
            return

        if events:
            await sync_events_batch(events, user, db)

    except Exception as e:
        logging.getLogger(__name__).warning(f"GCal sync failed: {e}")
