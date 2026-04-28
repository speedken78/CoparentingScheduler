"""
tests/unit/test_hash_chain.py

驗證 DATABASE.md §3.4 的 hash chain 演算法：
1. canonical_json 的穩定性（key 排序、無空白）
2. compute_row_hash 的確定性（相同輸入 → 相同輸出）
3. prev_hash 正確串鏈
4. None prev_hash 視為空字串
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.utils.hash_chain import canonical_json, compute_row_hash


CASE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
ENTITY_ID = UUID("00000000-0000-0000-0000-000000000003")
OCCURRED_AT = datetime(2026, 4, 21, 0, 0, 0, tzinfo=timezone.utc)


def _make_row(before=None, after=None):
    return {
        "case_id": CASE_ID,
        "actor_id": ACTOR_ID,
        "action": "create_custody_rule",
        "entity_type": "custody_rule",
        "entity_id": ENTITY_ID,
        "before_state": before,
        "after_state": after,
        "triggered_by": "human",
        "occurred_at": OCCURRED_AT,
    }


class TestCanonicalJson:
    def test_key_ordering(self):
        d = {"z": 1, "a": 2, "m": 3}
        result = canonical_json(d)
        assert result == '{"a":2,"m":3,"z":1}'

    def test_no_whitespace(self):
        result = canonical_json({"key": "value"})
        assert " " not in result

    def test_deterministic(self):
        d = {"b": [1, 2], "a": {"nested": True}}
        assert canonical_json(d) == canonical_json(d)

    def test_none_value(self):
        result = canonical_json({"k": None})
        assert result == '{"k":null}'


class TestComputeRowHash:
    def test_deterministic_same_input(self):
        row = _make_row()
        h1 = compute_row_hash(row, None)
        h2 = compute_row_hash(row, None)
        assert h1 == h2

    def test_is_sha256_hex(self):
        row = _make_row()
        h = compute_row_hash(row, None)
        assert len(h) == 64
        int(h, 16)  # 應為有效 hex

    def test_none_prev_hash_treated_as_empty_string(self):
        row = _make_row()
        h_none = compute_row_hash(row, None)
        h_empty = compute_row_hash(row, "")
        # None 與 "" 都視為空字串，結果相同
        assert h_none == h_empty

    def test_different_prev_hash_produces_different_hash(self):
        row = _make_row()
        h1 = compute_row_hash(row, None)
        h2 = compute_row_hash(row, "abc123")
        assert h1 != h2

    def test_chain_integrity(self):
        """第二筆的 prev_hash 應等於第一筆的 row_hash。"""
        row1 = _make_row(after={"rule_type": "weekly"})
        row2 = _make_row(after={"rule_type": "monthly_nth_weekday"})

        hash1 = compute_row_hash(row1, None)
        hash2 = compute_row_hash(row2, hash1)

        # 以第二筆的輸入重算，驗證一致
        assert hash2 == compute_row_hash(row2, hash1)

    def test_verify_chain_manually(self):
        """人工驗算：確認演算法與規格書描述一致。"""
        row = _make_row()
        payload = {
            "prev_hash": "",
            "case_id": str(CASE_ID),
            "actor_id": str(ACTOR_ID),
            "action": "create_custody_rule",
            "entity_type": "custody_rule",
            "entity_id": str(ENTITY_ID),
            "before_state": None,
            "after_state": None,
            "triggered_by": "human",
            "occurred_at": OCCURRED_AT.isoformat(),
        }
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
            .encode("utf-8")
        ).hexdigest()
        assert compute_row_hash(row, None) == expected
