import hashlib
import json


def canonical_json(d: dict) -> str:
    """產生穩定序列化，key 排序、無空白。"""
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_row_hash(row: dict, prev_hash: str | None) -> str:
    """
    row 應包含 audit_log 除了 id / row_hash 以外的所有欄位。
    prev_hash 為前一筆的 row_hash，第一筆為 None。
    """
    payload = {
        "prev_hash": prev_hash or "",
        "case_id": str(row["case_id"]),
        "actor_id": str(row["actor_id"]),
        "action": row["action"],
        "entity_type": row["entity_type"],
        "entity_id": str(row["entity_id"]),
        "before_state": row.get("before_state"),
        "after_state": row.get("after_state"),
        "triggered_by": row["triggered_by"],
        "occurred_at": row["occurred_at"].isoformat(),
    }
    s = canonical_json(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
