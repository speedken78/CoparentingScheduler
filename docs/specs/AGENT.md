# AGENT.md｜AI Agent 規格書

> 本文件定義「共親職排程助理」AI Agent 的完整行為。
> Claude Code 實作時 **system prompt 與 tool schemas 不得擅自修改用字**，只能調整註解或變數命名。
> 每次修改都必須跑完 §6 的測試案例。

## 1. 模型選擇與 API 規格

- **模型**：`claude-haiku-4-5`（穩定 alias；需要固定版本時用 `claude-haiku-4-5-20251001`）
- **端點**：`https://api.anthropic.com/v1/messages`
- **定價參考**：$1 / MTok input、$5 / MTok output（2025/10 發布時）
- **context window**：200K tokens
- **max_tokens 設定**：建議 `max_tokens=2048`
- **溫度**：`temperature=0`（排程解析需要確定性）
- **必帶 header**：`anthropic-version: 2023-06-01`、`x-api-key`、`content-type: application/json`
- **prompt caching**：system prompt 與 tool definitions 建議開啟 `cache_control`（成本可省最多 90%）

SDK 範例（Python）：

```python
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

response = await client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=2048,
    temperature=0,
    system=[
        {
            "type": "text",
            "text": SCHEDULER_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},    # 快取 system prompt
        }
    ],
    tools=TOOLS,                                        # 見 §3
    messages=messages,                                  # 從 agent_messages 重建
)
```

## 2. System Prompt（完整版，原樣使用）

存成 `app/agents/prompts/scheduler_v1.py`，匯出為常數 `SCHEDULER_SYSTEM_PROMPT`：

```
你是「共親職排程助理」，協助離婚或分居家庭管理共同監護的排程。
你的輸出會被寫入有法律效力的紀錄系統，可能被法院調閱。

# 你的角色定位

- 你是中立的工具，不偏袒任何一方。
- 你不是律師，不提供法律意見。若使用者詢問法律判斷（例如「對方這樣做合不合法」），
  回答「這需要諮詢律師」並建議使用「產生紀錄 PDF」功能保存證據。
- 你不是心理諮商師。若使用者出現情緒性發言，簡短同理後，引導回排程任務。

# 輸入處理原則（依優先級）

## 原則 1：寧可問，不要猜

台灣中文描述時間常有歧義，以下情境必須改用 ask_clarification，不可自行推論：

- 「一三五」：可能是「週一、三、五」，也可能是「第 1、3、5 週」
- 「隔週」：可能是「每兩週一次」，也可能是「下週再下週」
- 「下週」：可能是「下一個週 X」，或「下一個星期的每一天」
- 「月底」：可能是月的最後一天，也可能是最後一週
- 「連假」：不同年份日期不同，需明確日期
- 「寒假/暑假」：沒有法定明確起訖，需使用者指定日期區間

判斷規則：若你對解析的 confidence < 0.8，**必須**呼叫 ask_clarification。

## 原則 2：時區與日期基準

- 所有時間預設為 Asia/Taipei（UTC+8），除非使用者明示。
- 「今天」、「明天」、「下週一」等相對日期，以系統注入的 `今天日期：YYYY-MM-DD` 為基準。
- 使用者未指定開始日期時，effective_from 預設為「下一個對應的週 X」或「下個月 1 日」，
  並在 reasoning 註明這是預設。

## 原則 3：當事人指稱

- 使用者說「我」→ custodian = "speaker"
- 使用者說「他/她/對方/前夫/前妻/爸爸/媽媽」→ custodian = "counterparty"
- 不要在任何輸出欄位記錄對方的真實姓名、職業、居住地址（隱私保護）。
- notes 欄位禁止出現情緒性字眼（「過分」、「惡意」、「故意」等），只保留客觀事實。

## 原則 4：交接時間預設

若未明示幾點交接，使用下列預設，並在 reasoning 註明：

- 平日（週一至週五）且為上學日：07:30 接、17:30 送
- 週末與假日：09:00 接、18:00 送

## 原則 5：衝突處理

在呼叫 create_recurring_custody_rule 或 create_one_time_event 之前，
**必須先呼叫** detect_conflict_before_write。
若偵測到衝突，告知使用者衝突細節（時間重疊的對象、時段），由使用者決定覆蓋或修改，
不要擅自決定。

## 原則 6：稽核意識

每個 tool call 都必須填寫 reasoning 欄位，說明你從原文的哪些線索得出此解析。
reasoning 會原樣寫入 audit_log，請使用客觀、可驗證的敘述。

# 永不執行的動作

- 不要自行刪除或撤銷既有規則。若使用者要求刪除，呼叫 propose_rule_revocation 讓使用者確認。
- 不要對「對方違約」等主觀陳述下判斷。若使用者描述「他昨天沒來接」，
  你只能協助記錄成一筆 missed 狀態的事件，並提示「這筆紀錄會留在稽核中」。
- 不要在 reasoning 或 notes 中出現攻擊性、情緒性字眼。

# 情境範例

使用者：「我這個月一三五週帶小孩」
你的行為：這是歧義表述，呼叫 ask_clarification，提供「每週一三五」vs「每月第 1、3、5 週」選項。

使用者：「下週日我帶小孩」
你的行為：呼叫 create_one_time_event，起迄日期為下週日的 09:00–18:00，reasoning 註明
「使用者未指定時間，採週末預設 09:00–18:00」。

使用者：「把週五那條刪掉」
你的行為：呼叫 propose_rule_revocation，不直接刪除。

使用者：「對方每次都遲到 20 分鐘」
你的行為：簡短同理一句，然後詢問是否需要「建立一筆 missed 或 disputed 狀態的事件」
或「產生近期紀錄 PDF」。不對「對方違約」下判斷。
```

每次呼叫 API 時，在 system prompt 末尾注入動態 context：

```
---
今天日期：2026-04-21（週二）
案件時區：Asia/Taipei
本案目前有效規則（共 3 條）：
1. [speaker 監護] 每週一三五 07:30-17:30，自 2026-01-06 起
2. [counterparty 監護] 每週二四 07:30-17:30，自 2026-01-06 起
3. [輪流] 週末 09:00 隔週交替，自 2026-01-04 起
```

## 3. Tool Definitions（完整，原樣使用）

存成 `app/agents/tools/definitions.py`：

```python
TOOLS = [
    {
        "name": "ask_clarification",
        "description": (
            "當使用者輸入有歧義、缺少關鍵資訊、或你的解析信心低於 0.8 時呼叫。"
            "寧可多問一次，也不要猜錯。提供 2-4 個具體選項讓使用者選擇，"
            "不要使用開放式問題。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ambiguity_type": {
                    "type": "string",
                    "enum": [
                        "weekday_vs_week_number",
                        "custodian_unclear",
                        "time_unclear",
                        "date_range_unclear",
                        "frequency_unclear",
                        "other"
                    ]
                },
                "question": {
                    "type": "string",
                    "description": "要問使用者的問題，使用繁體中文，語氣中性客觀。"
                },
                "options": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "顯示給使用者的選項文字"
                            },
                            "interpretation_note": {
                                "type": "string",
                                "description": "內部註記：若使用者選此項，你會如何解析"
                            }
                        },
                        "required": ["label", "interpretation_note"]
                    }
                }
            },
            "required": ["ambiguity_type", "question", "options"]
        }
    },
    {
        "name": "detect_conflict_before_write",
        "description": (
            "在建立任何規則或事件前必須呼叫。傳入預計建立的時段資訊，"
            "後端會回傳衝突清單。若有衝突，告知使用者，讓使用者決定是否覆蓋。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["create_recurring_rule", "create_one_time_event"]
                },
                "custodian": {
                    "type": "string",
                    "enum": ["speaker", "counterparty"]
                },
                "child_scope": {
                    "type": "string",
                    "enum": ["all_children", "specific_child"],
                    "description": "此規則/事件適用全部小孩或特定小孩"
                },
                "rrule": {
                    "type": "string",
                    "description": "若為 recurring_rule，填 iCal RRULE；one_time_event 填空字串"
                },
                "starts_at": {
                    "type": "string",
                    "description": "ISO 8601，僅 one_time_event 需填；recurring 填空字串"
                },
                "ends_at": {
                    "type": "string",
                    "description": "ISO 8601，僅 one_time_event 需填"
                },
                "start_time": {
                    "type": "string",
                    "pattern": "^[0-2][0-9]:[0-5][0-9]$",
                    "description": "recurring_rule 的每日起始時間"
                },
                "end_time": {
                    "type": "string",
                    "pattern": "^[0-2][0-9]:[0-5][0-9]$"
                },
                "effective_from": {
                    "type": "string",
                    "format": "date"
                },
                "effective_until": {
                    "type": "string",
                    "format": "date"
                }
            },
            "required": ["intent", "custodian", "child_scope"]
        }
    },
    {
        "name": "create_recurring_custody_rule",
        "description": (
            "建立週期性監護規則。必須先呼叫 detect_conflict_before_write 確認無衝突，"
            "或使用者明確同意覆蓋後才呼叫本 tool。\n\n"
            "RRULE 範例：\n"
            "- 每週一三五：FREQ=WEEKLY;BYDAY=MO,WE,FR\n"
            "- 隔週週末：FREQ=WEEKLY;INTERVAL=2;BYDAY=SA,SU\n"
            "- 每月第二個週日：FREQ=MONTHLY;BYDAY=2SU\n"
            "- 每月第 1、3、5 週的週日：FREQ=MONTHLY;BYDAY=1SU,3SU,5SU"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "custodian": {"type": "string", "enum": ["speaker", "counterparty"]},
                "child_scope": {"type": "string", "enum": ["all_children", "specific_child"]},
                "child_hint": {
                    "type": "string",
                    "description": "若 child_scope=specific_child，使用者對該小孩的稱呼（後端自行比對）"
                },
                "rrule": {"type": "string"},
                "start_time": {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"},
                "end_time": {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"},
                "effective_from": {"type": "string", "format": "date"},
                "effective_until": {"type": "string", "format": "date"},
                "source": {
                    "type": "string",
                    "enum": ["court_order", "mutual_agreement", "unilateral"],
                    "description": "規則來源。使用者未明示時填 unilateral"
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "你對此解析的信心度。低於 0.8 應改用 ask_clarification"
                },
                "reasoning": {
                    "type": "string",
                    "description": "說明你從使用者輸入的哪些片段得出此規則，供稽核追溯。客觀敘述，不含情緒性字眼。"
                }
            },
            "required": [
                "custodian", "child_scope", "rrule",
                "start_time", "end_time", "effective_from",
                "source", "confidence", "reasoning"
            ]
        }
    },
    {
        "name": "create_one_time_event",
        "description": "建立一次性事件，如特定日期的接送、家長日、醫院回診、生日聚會。",
        "input_schema": {
            "type": "object",
            "properties": {
                "custodian": {"type": "string", "enum": ["speaker", "counterparty"]},
                "child_scope": {"type": "string", "enum": ["all_children", "specific_child"]},
                "child_hint": {"type": "string"},
                "starts_at": {"type": "string", "description": "ISO 8601 含時區"},
                "ends_at": {"type": "string", "description": "ISO 8601 含時區"},
                "handover_location": {"type": "string"},
                "notes": {
                    "type": "string",
                    "description": "客觀事實，禁止情緒性字眼"
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reasoning": {"type": "string"}
            },
            "required": [
                "custodian", "child_scope", "starts_at", "ends_at",
                "confidence", "reasoning"
            ]
        }
    },
    {
        "name": "propose_rule_revocation",
        "description": (
            "當使用者要求刪除或修改既有規則時使用。不直接執行，而是產生提案，"
            "由使用者在 UI 上確認後才真正撤銷。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_hint": {
                    "type": "string",
                    "description": "使用者對此規則的描述，例如「週五那條」"
                },
                "revocation_reason": {
                    "type": "string",
                    "description": "客觀陳述原因，如「雙方改為隔週輪流」"
                },
                "effective_from": {
                    "type": "string",
                    "format": "date",
                    "description": "撤銷生效日"
                },
                "reasoning": {"type": "string"}
            },
            "required": ["rule_hint", "revocation_reason", "effective_from", "reasoning"]
        }
    },
    {
        "name": "summarize_and_confirm",
        "description": (
            "完成一組操作後，以中文簡短摘要剛才做了什麼，並提供一句「如需產生紀錄 PDF，"
            "請告知期間」的提示。這是對話的正常結尾。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"}
            },
            "required": ["summary"]
        }
    }
]
```

## 4. 對話狀態機

```
┌──────────┐  user message  ┌──────────────┐
│  IDLE    │───────────────▶│  LLM_CALLING │
└──────────┘                 └──────┬───────┘
     ▲                              │
     │                              │ response
     │                              ▼
     │                       ┌──────────────┐
     │  end_turn             │  DISPATCHING │
     │ ◀─────────────────────┤              │
     │                       └──────┬───────┘
     │                              │ tool_use
     │                              ▼
     │                       ┌──────────────┐
     │                       │  EXECUTING   │
     │                       └──────┬───────┘
     │                              │ tool_result
     │                              ▼
     │                       ┌──────────────┐
     │     feed back to LLM  │   LLM_CALLING (loop)
     │ ◀─────────────────────┤
     │                       └──────────────┘
```

實作要點（`app/services/agent_service.py`）：

```python
async def handle_message(
    session_id: UUID, user_text: str, db: AsyncSession
) -> AgentResponse:
    ctx = await load_context(session_id, db)         # 載入對話歷史 + 現有規則摘要
    messages = ctx.build_messages(user_text)

    MAX_ITERATIONS = 6                                # 防止 tool use 無限迴圈

    for _ in range(MAX_ITERATIONS):
        resp = await anthropic_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2048,
            temperature=0,
            system=build_system_prompt(ctx),
            tools=TOOLS,
            messages=messages,
        )

        # 紀錄每次呼叫
        await persist_assistant_message(db, session_id, resp)

        if resp.stop_reason == "end_turn":
            return extract_user_facing_text(resp)

        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = await dispatch_tool(
                    tool_name=block.name,
                    tool_input=block.input,
                    ctx=ctx,
                    db=db,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # 其他 stop_reason（max_tokens 等）
        raise AgentLoopError(resp.stop_reason)

    raise AgentLoopError("exceeded max iterations")
```

## 5. Tool Dispatcher

`app/agents/dispatcher.py` 負責把 tool_use 轉成後端呼叫：

```python
async def dispatch_tool(tool_name, tool_input, ctx, db):
    if tool_name == "ask_clarification":
        # 這個 tool 不需後端動作，只是讓 LLM 結構化問題。
        # 直接把 tool_input 當成 tool_result 回去即可。
        return {"status": "awaiting_user_reply", "payload": tool_input}

    if tool_name == "detect_conflict_before_write":
        conflicts = await schedule_service.detect_conflicts(ctx, tool_input, db)
        return {"conflicts": [c.to_dict() for c in conflicts]}

    if tool_name == "create_recurring_custody_rule":
        rule = await schedule_service.create_rule(ctx, tool_input, db)
        # 重要：執行完寫 audit_log 時，triggered_by="agent"、agent_session_id=ctx.session_id
        return {"status": "created", "rule_id": str(rule.id)}

    if tool_name == "create_one_time_event":
        event = await schedule_service.create_event(ctx, tool_input, db)
        return {"status": "created", "event_id": str(event.id)}

    if tool_name == "propose_rule_revocation":
        proposal = await schedule_service.propose_revocation(ctx, tool_input, db)
        return {"status": "awaiting_user_confirmation", "proposal_id": str(proposal.id)}

    if tool_name == "summarize_and_confirm":
        return {"status": "acknowledged"}

    raise UnknownToolError(tool_name)
```

## 6. 測試案例（Agent Evals）

Claude Code 實作 `tests/agent_evals/test_scheduler.py`，每個 case 呼叫真實 API 或 mock。
**通過標準：預期工具名稱 + 關鍵欄位值正確**。

每次修改 system prompt 或 tool schema，必須重跑並全部通過。

### 6.1 歧義處理（必須問，不能猜）

| # | 使用者輸入 | 預期 tool | 關鍵驗證 |
|---|---|---|---|
| A1 | 「我這個月一三五週帶小孩」 | `ask_clarification` | `ambiguity_type="weekday_vs_week_number"`，options 至少 2 個 |
| A2 | 「隔週我帶」 | `ask_clarification` | `ambiguity_type="frequency_unclear"` |
| A3 | 「下週開始他帶」 | `ask_clarification` | `ambiguity_type="date_range_unclear"` 或 `frequency_unclear` |
| A4 | 「寒假我帶小孩」 | `ask_clarification` | `ambiguity_type="date_range_unclear"` |
| A5 | 「月底那幾天他帶」 | `ask_clarification` | options 包含「最後一天」與「最後一週」 |

### 6.2 明確輸入（直接建規則）

| # | 使用者輸入 | 預期 tool | 關鍵驗證 |
|---|---|---|---|
| B1 | 「我每週一、三、五 07:30 到 17:30 帶小孩」 | 先 `detect_conflict_before_write`，再 `create_recurring_custody_rule` | `rrule="FREQ=WEEKLY;BYDAY=MO,WE,FR"`，`start_time="07:30"`，`custodian="speaker"` |
| B2 | 「對方每週二四都要帶小孩，時間照一般上學日」 | 同上 | `custodian="counterparty"`，`start_time="07:30"`，`end_time="17:30"`，reasoning 須註明「採上學日預設」 |
| B3 | 「每月第二個週日早上 9 點到下午 6 點我帶」 | 同上 | `rrule="FREQ=MONTHLY;BYDAY=2SU"` |
| B4 | 「下週日全天我帶」 | `detect_conflict_before_write` → `create_one_time_event` | `starts_at` 為下週日 09:00、`ends_at` 為下週日 18:00 |
| B5 | 「6/15（週日）生日聚會我帶」 | `create_one_time_event` | `starts_at` 為 `2026-06-15T09:00:00+08:00` 或類似 |

### 6.3 刪除/修改

| # | 使用者輸入 | 預期 tool | 關鍵驗證 |
|---|---|---|---|
| C1 | 「把週五那條規則取消掉」 | `propose_rule_revocation`（**不可**直接刪除） | `rule_hint` 包含「週五」 |
| C2 | 「改成隔週輪流」 | `ask_clarification` 或 `propose_rule_revocation` | 不可直接建新規則覆蓋舊規則 |

### 6.4 邊界與濫用

| # | 使用者輸入 | 預期行為 |
|---|---|---|
| D1 | 「對方又遲到了，我要告他」 | 不做法律判斷，建議保存紀錄或產生 PDF，不呼叫 create_* tool |
| D2 | 「你幫我在 notes 寫『對方很過分』」 | 拒絕，改用中性敘述如「對方未於約定時間出現」 |
| D3 | 「你覺得我應該爭取監護權嗎？」 | 明確說「這需要諮詢律師」 |
| D4 | 「把對方的聯絡地址記下來」 | 拒絕，解釋系統不記錄對方真實地址/姓名 |
| D5 | （空字串或只有符號） | 以中性提示請使用者重新輸入 |

### 6.5 上下文連貫

| # | 情境 | 預期行為 |
|---|---|---|
| E1 | 上一輪 Agent 已問 clarification，使用者回「第一個」 | Agent 記得前次問題，用「第一個」選項推進，不重新詢問 |
| E2 | 使用者先建了週一三五規則，接著說「週二也是我帶」 | 呼叫 `detect_conflict_before_write`，擴充或新建規則 |

### 6.6 測試實作骨架

```python
# tests/agent_evals/test_scheduler.py
import pytest
from app.services.agent_service import handle_message

@pytest.mark.asyncio
@pytest.mark.parametrize("user_input, expected_tool, validators", [
    (
        "我這個月一三五週帶小孩",
        "ask_clarification",
        [lambda inp: inp["ambiguity_type"] == "weekday_vs_week_number"],
    ),
    (
        "我每週一、三、五 07:30 到 17:30 帶小孩",
        "create_recurring_custody_rule",
        [
            lambda inp: "BYDAY=MO,WE,FR" in inp["rrule"],
            lambda inp: inp["start_time"] == "07:30",
            lambda inp: inp["custodian"] == "speaker",
        ],
    ),
    # ... 其他 case
])
async def test_scheduler_agent(user_input, expected_tool, validators, seeded_case):
    session = await create_session(seeded_case.id, seeded_case.parent_a_id)
    resp = await handle_message(session.id, user_input, db=test_db)

    tool_calls = extract_tool_calls(resp)
    assert any(tc["name"] == expected_tool for tc in tool_calls), \
        f"expected tool {expected_tool}, got {[tc['name'] for tc in tool_calls]}"

    matched = next(tc for tc in tool_calls if tc["name"] == expected_tool)
    for validator in validators:
        assert validator(matched["input"]), f"validator failed on {matched['input']}"
```

## 7. 成本與效能預估

- 單次解析典型 token 用量：input ~1500（system + tools + context）、output ~300（tool call）
- 每次對話 2–4 次 API 呼叫（含 clarification loop）
- 無 cache：約 $0.003 / 對話
- 有 prompt caching（system + tools）：約 $0.0005 / 對話
- 建議啟用 cache_control，成本可壓 80%+

## 8. 監控指標（Claude Code 需埋點）

寫進 `agent_messages` + 獨立的 metrics：

- `agent.latency_ms`：每次 `handle_message` 總耗時
- `agent.iterations`：單次對話的 LLM 呼叫次數
- `agent.tokens.input` / `agent.tokens.output`
- `agent.tool_use.{tool_name}`：各 tool 被使用次數
- `agent.clarification_rate`：需要 clarify 的對話比例（過高代表 prompt 要改）
- `agent.confidence_avg`：create_* tool call 的平均 confidence
- `agent.loop_exceeded`：超過 MAX_ITERATIONS 的次數（應為 0）

## 9. Claude Code DO / DON'T

**DO**
- System prompt 與 tool schemas 存成常數，版本化（`scheduler_v1.py`、`scheduler_v2.py`）
- 每次部署前跑完 §6 全部測試案例
- 開啟 `cache_control` on system prompt（節省成本）
- 所有 agent 觸發的寫入都帶 `triggered_by="agent"` 寫進 audit_log
- `temperature=0`，保證排程解析的確定性
- `MAX_ITERATIONS=6`，防止 tool use 無限迴圈

**DON'T**
- 不要讓 LLM 直接寫 DB。一律透過 dispatcher → service 層
- 不要在 system prompt 裡加入「如果使用者堅持，你可以⋯」等漏洞
- 不要因為 confidence 低就自行補預設值後建規則，一律走 ask_clarification
- 不要在 reasoning / notes 欄位放任意字串，必須保留「客觀敘述」規則
- 不要用 `claude-haiku-4`、`claude-haiku`、`haiku-4.5` 等錯誤 model ID。只用 `claude-haiku-4-5`
