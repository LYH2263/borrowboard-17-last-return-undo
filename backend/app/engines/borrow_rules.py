"""One active loan per item + overdue detection."""

# 撤销归还时的冲突处置：整单失败保持现况 / 挤掉新借让原笔回到在借
UNDO_DISPOSITIONS = ("fail", "bump")

def can_lend(item_status: str, active_loans: int) -> dict:
    if item_status != "available":
        return {"ok": False, "reason": "item_not_available"}
    if active_loans > 0:
        return {"ok": False, "reason": "already_on_loan"}
    return {"ok": True, "reason": ""}

def is_overdue(due_date: str, today: str, loan_status: str) -> bool:
    if loan_status != "active":
        return False
    return bool(due_date) and due_date < today

def classify_loans(loans: list[dict], today: str) -> dict:
    active, overdue, returned, bumped = [], [], [], []
    for L in loans:
        st = L.get("status")
        if st == "returned":
            returned.append(L)
        elif st == "bumped":
            bumped.append(L)
        elif is_overdue(L.get("due_date"), today, st):
            overdue.append({**L, "overdue": True})
        elif st == "active":
            active.append({**L, "overdue": False})
    return {"active": active, "overdue": overdue, "returned": returned, "bumped": bumped}

def latest_returned_id(loans: list[dict]):
    """最近一笔成功 returned 的 loan id —— 唯一可撤销的一笔。"""
    ret = [l for l in loans if l.get("status") == "returned" and l.get("returned_at")]
    if not ret:
        return None
    return max(ret, key=lambda l: (l.get("returned_at") or "", l.get("id") or 0))["id"]

def can_undo_return(loan_status: str, is_latest: bool, reason: str) -> dict:
    if loan_status != "returned":
        return {"ok": False, "reason": "not_returned"}
    if not is_latest:
        return {"ok": False, "reason": "not_latest_return"}
    if not (reason or "").strip():
        return {"ok": False, "reason": "reason_required"}
    return {"ok": True, "reason": ""}

def undo_conflicts(item_status: str, active_loans: int) -> bool:
    """归还后该物又被借出通过 -> 撤销会撞上别人的在借。"""
    return item_status == "on_loan" or active_loans > 0
