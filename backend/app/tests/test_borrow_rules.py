from app.engines.borrow_rules import (
    can_lend, can_undo_return, classify_loans, is_overdue,
    latest_returned_id, undo_conflicts,
)

def test_mutex():
    assert can_lend("available", 0)["ok"]
    assert can_lend("available", 1)["reason"] == "already_on_loan"
    assert can_lend("retired", 0)["ok"] is False

def test_overdue():
    assert is_overdue("2020-01-01", "2026-01-01", "active")
    assert not is_overdue("2020-01-01", "2026-01-01", "returned")

def test_classify():
    r = classify_loans([
        {"id": 1, "status": "active", "due_date": "2020-01-01"},
        {"id": 2, "status": "active", "due_date": "2099-01-01"},
        {"id": 3, "status": "returned", "due_date": "2020-01-01"},
    ], "2026-01-01")
    assert len(r["overdue"]) == 1 and len(r["active"]) == 1 and len(r["returned"]) == 1

def test_latest_returned():
    loans = [
        {"id": 1, "status": "returned", "returned_at": "2026-01-01"},
        {"id": 2, "status": "returned", "returned_at": "2026-02-01"},
        {"id": 3, "status": "active", "returned_at": None},
    ]
    assert latest_returned_id(loans) == 2
    assert latest_returned_id([loans[2]]) is None

def test_undo_rules():
    # 不是最近一笔的历史已还必须失败
    assert can_undo_return("returned", False, "填错了")["reason"] == "not_latest_return"
    # 缺原因字失败
    assert can_undo_return("returned", True, "  ")["reason"] == "reason_required"
    assert can_undo_return("active", True, "x")["reason"] == "not_returned"
    assert can_undo_return("returned", True, "填错了")["ok"]

def test_undo_conflicts():
    assert undo_conflicts("on_loan", 1)
    assert undo_conflicts("available", 1)
    assert not undo_conflicts("available", 0)

def test_classify_bumped():
    r = classify_loans([{"id": 9, "status": "bumped", "due_date": "2020-01-01"}], "2026-01-01")
    assert len(r["bumped"]) == 1
    assert not r["overdue"] and not r["returned"] and not r["active"]
