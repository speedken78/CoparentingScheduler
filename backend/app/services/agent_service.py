# app/services/agent_service.py
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone

import vertexai
from vertexai.generative_models import (
    Content,
    FunctionDeclaration,
    GenerationConfig,
    GenerativeModel,
    Part,
    Tool,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.agents.context import AgentContext, load_context
from app.agents.tools.definitions import TOOLS
from app.agents.prompts.scheduler_v1 import build_system_prompt, PROMPT_VERSION
from app.agents.dispatcher import dispatch_tool
from app.models.agent_session import AgentSession, AgentMessage
from app.services.audit_service import log as audit_log
from app.utils.errors import AgentLoopError, UnknownToolError

MAX_ITERATIONS = 6

# 初始化 Vertex AI（Cloud Run 上使用 ADC；本地需 gcloud auth application-default login）
_init_kwargs: dict = {"location": settings.VERTEX_AI_LOCATION}
if settings.VERTEX_AI_PROJECT:
    _init_kwargs["project"] = settings.VERTEX_AI_PROJECT
vertexai.init(**_init_kwargs)

# 快取編譯好的 Tool 物件（Tool definitions 不變）
_GEMINI_TOOLS: list[Tool] | None = None


def _get_gemini_tools() -> list[Tool]:
    global _GEMINI_TOOLS
    if _GEMINI_TOOLS is None:
        declarations = [
            FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["input_schema"],
            )
            for t in TOOLS
        ]
        _GEMINI_TOOLS = [Tool(function_declarations=declarations)]
    return _GEMINI_TOOLS


def _to_gemini_contents(messages: list[dict]) -> list[Content]:
    """
    把儲存在 DB 裡的 Anthropic 相容訊息格式轉成 Gemini Content 物件。

    Anthropic format：
      user: {"role": "user", "content": "text" | [blocks]}
      assistant: {"role": "assistant", "content": [text_block | tool_use_block]}
      tool results: {"role": "user", "content": [tool_result_block]}

    Gemini format：
      user: Content(role="user", parts=[Part.from_text(...)])
      model: Content(role="model", parts=[Part.from_text(...), Part(function_call=...)])
      tool results: Content(role="user", parts=[Part.from_function_response(...)])
    """
    # 第一遍：建立 tool_use_id → tool_name 對照表（tool_result 轉換時需要名稱）
    id_to_name: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") == "assistant":
            for block in (msg.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    id_to_name[block.get("id", "")] = block.get("name", "")

    contents: list[Content] = []
    for msg in messages:
        role = msg.get("role", "user")
        raw = msg.get("content", "")
        g_role = "model" if role == "assistant" else "user"

        # 純文字訊息
        if isinstance(raw, str):
            if raw:
                contents.append(Content(role=g_role, parts=[Part.from_text(raw)]))
            continue

        if not isinstance(raw, list) or not raw:
            continue

        # 判斷是否為 tool_result 訊息
        is_tool_results = role == "user" and all(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in raw
        )

        if is_tool_results:
            parts: list[Part] = []
            for block in raw:
                if not isinstance(block, dict):
                    continue
                uid = block.get("tool_use_id", "")
                name = block.get("tool_name") or id_to_name.get(uid) or "tool"
                raw_c = block.get("content", "{}")
                try:
                    resp_dict = json.loads(raw_c) if isinstance(raw_c, str) else raw_c
                except Exception:
                    resp_dict = {"result": str(raw_c)}
                parts.append(Part.from_function_response(name=name, response=resp_dict))
            if parts:
                contents.append(Content(role="user", parts=parts))
            continue

        # 一般 content block 列表（text / tool_use）
        parts = []
        for block in raw:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                parts.append(Part.from_text(block["text"]))
            elif btype == "tool_use":
                try:
                    parts.append(Part.from_dict({
                        "function_call": {
                            "name": block.get("name", ""),
                            "args": block.get("input", {}),
                        }
                    }))
                except Exception:
                    parts.append(Part.from_text(
                        f"[tool call: {block.get('name')} {json.dumps(block.get('input', {}))}]"
                    ))
        if parts:
            contents.append(Content(role=g_role, parts=parts))

    return contents


async def get_or_create_session(
    case_id: UUID,
    user_id: UUID,
    session_id: UUID | None,
    db: AsyncSession,
) -> UUID:
    if session_id is None:
        new_session = AgentSession(id=uuid4(), case_id=case_id, user_id=user_id)
        db.add(new_session)
        await db.flush()
        return new_session.id

    session = await db.get(AgentSession, session_id)
    if not session or str(session.case_id) != str(case_id) or \
       str(session.user_id) != str(user_id):
        raise ValueError("Invalid session_id")
    return session_id


async def persist_message(
    db: AsyncSession,
    session_id: UUID,
    role: str,
    content,
    tool_use_id: str | None = None,
    tool_name: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
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
    async with db.begin_nested():
        # 1. 取得或建立 session
        sid = await get_or_create_session(case_id, user_id, session_id, db)

        # 2. 載入 context（歷史訊息 + 現有規則）
        ctx = await load_context(sid, case_id, user_id, db)

        # 3. 新增使用者訊息
        ctx.append_user_message(user_text)
        await persist_message(db, sid, "user", user_text)

        # 4. Audit log：使用者輸入
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

        # 5. 建立 Gemini model（每次請求帶入最新 system prompt）
        model = GenerativeModel(
            settings.VERTEX_AI_MODEL,
            system_instruction=build_system_prompt(
                today_date=ctx.today_label(),
                case_timezone=ctx.case_timezone,
                active_rules=ctx.active_rules,
            ),
        )
        gen_config = GenerationConfig(temperature=0.0, max_output_tokens=2048)
        gemini_tools = _get_gemini_tools()

        actions_taken: list[dict] = []
        clarification_payload: dict | None = None
        reply = "（已完成）"

        # 6. 狀態機主迴圈
        for iteration in range(MAX_ITERATIONS):
            contents = _to_gemini_contents(ctx.truncated_messages())
            resp = await model.generate_content_async(
                contents=contents,
                tools=gemini_tools,
                generation_config=gen_config,
            )

            candidate = resp.candidates[0]
            response_parts = candidate.content.parts

            # 把 assistant 訊息轉成儲存格式（與原 Anthropic 格式相容）
            assistant_blocks: list[dict] = []
            for part in response_parts:
                if hasattr(part, "text") and part.text:
                    assistant_blocks.append({"type": "text", "text": part.text})
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": f"{fc.name}-{iteration}",
                        "name": fc.name,
                        "input": dict(fc.args),
                    })

            await persist_message(
                db, sid, "assistant",
                content=assistant_blocks,
                model=settings.VERTEX_AI_MODEL,
                input_tokens=getattr(resp.usage_metadata, "prompt_token_count", None),
                output_tokens=getattr(resp.usage_metadata, "candidates_token_count", None),
            )
            ctx.append_assistant_response(assistant_blocks)

            # 找出所有 function_call parts
            fc_parts = [
                p for p in response_parts
                if hasattr(p, "function_call") and p.function_call
            ]

            if not fc_parts:
                # 沒有 function call → 結束
                reply = "\n".join(
                    p.text for p in response_parts
                    if hasattr(p, "text") and p.text
                ) or "（已完成）"
                break

            # 有 function call → 逐一 dispatch
            tool_results: list[dict] = []
            for part in fc_parts:
                fc = part.function_call
                tool_name = fc.name
                tool_input = dict(fc.args)
                tool_id = f"{tool_name}-{iteration}"

                await audit_log(
                    db,
                    case_id=case_id,
                    actor_id=user_id,
                    action="agent_tool_call",
                    entity_type="agent_session",
                    entity_id=sid,
                    after_state={
                        "tool": tool_name,
                        "input": tool_input,
                        "reasoning": tool_input.get("reasoning", ""),
                    },
                    triggered_by="agent",
                    agent_session_id=sid,
                )

                result = await dispatch_tool(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    ctx=ctx,
                    db=db,
                )

                if tool_name == "ask_clarification":
                    clarification_payload = result

                if tool_name == "summarize_and_confirm":
                    await audit_log(
                        db,
                        case_id=case_id,
                        actor_id=user_id,
                        action="agent_session_summarized",
                        entity_type="agent_session",
                        entity_id=sid,
                        after_state={"summary": tool_input.get("summary", "")},
                        triggered_by="agent",
                        agent_session_id=sid,
                    )

                actions_taken.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "tool_name": tool_name,   # Gemini 轉換時需要此欄位
                    "content": json.dumps(result, ensure_ascii=False),
                })

            ctx.append_tool_results(tool_results)
            await persist_message(db, sid, "tool_result", tool_results)

        else:
            raise AgentLoopError("Exceeded max iterations without finishing")

        # 7. 更新 session last_active_at
        session = await db.get(AgentSession, sid)
        if session:
            session.last_active_at = datetime.now(timezone.utc)

    # GCal 同步在 savepoint release 後觸發
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
    import logging
    from app.services.gcal_sync_service import sync_events_batch
    from app.repositories.event_repo import EventRepository

    try:
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
