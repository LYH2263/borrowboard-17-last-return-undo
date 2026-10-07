from datetime import date, datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect, write_tx
from app.engines.borrow_rules import (
    UNDO_DISPOSITIONS, can_lend, can_undo_return, classify_loans,
    latest_returned_id, undo_conflicts,
)

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

@app.get("/api/items")
def items():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM items")]; c.close(); return rows

@app.get("/api/board")
def board():
    c = connect()
    available = [dict(r) for r in c.execute("SELECT * FROM items WHERE status='available'")]
    loans = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.status='active'""")]
    c.close()
    cls = classify_loans(loans, date.today().isoformat())
    return {
        "available": available,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {"available": len(available), "active": len(cls["active"]), "overdue": len(cls["overdue"])},
    }

class ItemIn(BaseModel):
    title: str
    owner: str

@app.post("/api/items")
def add_item(body: ItemIn):
    c = connect()
    cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.owner, "available", "clean"))
    c.commit(); iid = cur.lastrowid; c.close(); return {"id": iid}

class LendIn(BaseModel):
    borrower: str
    due_date: str

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    with write_tx() as c:
        item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not item: raise HTTPException(404, "item")
        active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
        check = can_lend(item["status"], active)
        if not check["ok"]:
            raise HTTPException(409, check["reason"])
        cur = c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (iid, body.borrower, "active", body.due_date, datetime.now(timezone.utc).isoformat()))
        c.execute("UPDATE items SET status='on_loan' WHERE id=?", (iid,))
        lid = cur.lastrowid
    return {"loan_id": lid}

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int):
    with write_tx() as c:
        loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
        if not loan: raise HTTPException(404, "loan")
        if loan["status"] != "active":
            raise HTTPException(400, "not_active")
        c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
                  (datetime.now(timezone.utc).isoformat(), lid))
        c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
    return {"ok": True}

class UndoPreviewIn(BaseModel):
    reason: str = ""

def _undo_context(c, lid):
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: raise HTTPException(404, "loan")
    latest = latest_returned_id(
        [dict(r) for r in c.execute("SELECT * FROM loans WHERE status='returned'")])
    item = c.execute("SELECT * FROM items WHERE id=?", (loan["item_id"],)).fetchone()
    actives = [dict(r) for r in c.execute(
        "SELECT * FROM loans WHERE item_id=? AND status='active'", (loan["item_id"],))]
    return loan, latest, item, actives

@app.post("/api/loans/{lid}/undo-return/preview")
def undo_return_preview(lid: int, body: UndoPreviewIn):
    # 预览只读不落库：可借栏集合不变
    c = connect()
    loan, latest, item, actives = _undo_context(c, lid)
    c.close()
    check = can_undo_return(loan["status"], loan["id"] == latest, body.reason)
    return {
        "ok": check["ok"],
        "reason": check["reason"],
        "conflict": undo_conflicts(item["status"] if item else "available", len(actives)),
        "blocking_loan": actives[0] if actives else None,
        "dispositions": list(UNDO_DISPOSITIONS),
        "board_unchanged": True,
    }

class UndoIn(BaseModel):
    reason: str = ""
    disposition: str = "fail"  # fail=整单失败保持现况 / bump=挤掉新借让原笔回到在借

@app.post("/api/loans/{lid}/undo-return")
def undo_return(lid: int, body: UndoIn):
    if body.disposition not in UNDO_DISPOSITIONS:
        raise HTTPException(400, "bad_disposition")
    with write_tx() as c:
        loan, latest, item, actives = _undo_context(c, lid)
        check = can_undo_return(loan["status"], loan["id"] == latest, body.reason)
        if not check["ok"]:
            raise HTTPException(409 if check["reason"] == "not_latest_return" else 400, check["reason"])
        conflict = undo_conflicts(item["status"] if item else "available", len(actives))
        if conflict and body.disposition == "fail":
            raise HTTPException(409, "undo_conflict")  # 整单失败保持现况
        now = datetime.now(timezone.utc).isoformat()
        if conflict:  # 挤掉新借让原笔回到在借
            for a in actives:
                c.execute("UPDATE loans SET status='bumped', bumped_by=? WHERE id=?", (lid, a["id"]))
        c.execute(
            "UPDATE loans SET status='active', returned_at=NULL, undo_reason=?, undo_disposition=?, undone_at=? WHERE id=?",
            (body.reason.strip(), body.disposition, now, lid))
        c.execute("UPDATE items SET status='on_loan' WHERE id=?", (loan["item_id"],))
    return {"ok": True, "conflict": conflict, "disposition": body.disposition}

@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    c.close()
    return classify_loans(rows, date.today().isoformat())

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows
