# app/agents/tools/definitions.py

TOOLS: list[dict] = [
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

# Tool 名稱集合，用於 dispatcher 的快速驗證
KNOWN_TOOL_NAMES: set[str] = {t["name"] for t in TOOLS}
