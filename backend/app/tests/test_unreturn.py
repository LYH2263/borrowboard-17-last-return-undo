import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import connect as db_connect

    with TestClient(app) as c:
        cc = db_connect()
        cc.execute("DELETE FROM loans")
        cc.execute("DELETE FROM items")
        cc.commit()
        cc.close()
        yield c


def _add_item(client, title="电钻"):
    r = client.post("/api/items", json={"title": title, "owner": "老周"})
    assert r.status_code == 200
    return r.json()["id"]


def _lend(client, iid, borrower="邻居甲", due="2099-01-01"):
    r = client.post(f"/api/items/{iid}/lend", json={"borrower": borrower, "due_date": due})
    assert r.status_code == 200, r.text
    return r.json()["loan_id"]


def _statuses(client, iid, lid):
    from app.db import connect
    c = connect()
    item = c.execute("SELECT status s FROM items WHERE id=?", (iid,)).fetchone()["s"]
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    c.close()
    return item, dict(loan)


def test_unreturn_latest_restores_active_and_hides_from_available(client):
    iid = _add_item(client)
    lid = _lend(client, iid)
    assert client.post(f"/api/loans/{lid}/return").status_code == 200
    item, loan = _statuses(client, iid, lid)
    assert (item, loan["status"]) == ("available", "returned")

    r = client.post(f"/api/loans/{lid}/unreturn", json={"reason": "搞错了，物其实没还"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "conflict": False, "bumped_loan_ids": []}

    item, loan = _statuses(client, iid, lid)
    assert item == "on_loan"
    assert loan["status"] == "active"
    assert loan["returned_at"] is None
    assert loan["unreturn_reason"] == "搞错了，物其实没还"
    assert loan["rev_conflict"] is None
    assert loan["unreturned_at"]

    board = client.get("/api/board").json()
    assert iid not in [i["id"] for i in board["available"]]
    assert lid in [l["id"] for l in board["active"]]

    rec = client.get("/api/loans").json()
    assert lid in [l["id"] for l in rec["active"]]
    assert lid not in [l["id"] for l in rec["returned"]]


@pytest.mark.parametrize("payload", [{}, {"reason": ""}, {"reason": "   "}])
def test_unreturn_without_reason_fails(client, payload):
    iid = _add_item(client)
    lid = _lend(client, iid)
    client.post(f"/api/loans/{lid}/return")
    r = client.post(f"/api/loans/{lid}/unreturn", json=payload)
    assert r.status_code == 400
    assert "reason_required" in r.text
    item, loan = _statuses(client, iid, lid)
    assert (item, loan["status"]) == ("available", "returned")


def test_unreturn_non_latest_returned_must_fail(client):
    iid = _add_item(client)
    a = _lend(client, iid, borrower="甲")
    client.post(f"/api/loans/{a}/return")
    b = _lend(client, iid, borrower="乙")
    client.post(f"/api/loans/{b}/return")

    r = client.post(f"/api/loans/{a}/unreturn", json={"reason": "误操作"})
    assert r.status_code == 409
    assert "not_latest_return" in r.text
    item, loan_a = _statuses(client, iid, a)
    _, loan_b = _statuses(client, iid, b)
    # 整单失败保持现况
    assert item == "available"
    assert loan_a["status"] == "returned" and loan_b["status"] == "returned"


def test_unreturn_latest_is_global_across_items(client):
    iid_a = _add_item(client, "电钻")
    iid_b = _add_item(client, "折叠桌")
    la = _lend(client, iid_a, borrower="甲")
    client.post(f"/api/loans/{la}/return")
    lb = _lend(client, iid_b, borrower="乙")
    client.post(f"/api/loans/{lb}/return")

    # 电钻那笔虽是该物最近归还，但不是全局最近一笔已还
    r = client.post(f"/api/loans/{la}/unreturn", json={"reason": "误操作"})
    assert r.status_code == 409 and "not_latest_return" in r.text
    # 全局最近一笔（折叠桌）可撤
    assert client.post(f"/api/loans/{lb}/unreturn",
                       json={"reason": "误操作"}).status_code == 200
    item_b, loan_b = _statuses(client, iid_b, lb)
    assert (item_b, loan_b["status"]) == ("on_loan", "active")
    # 撤销后它不再是 returned，电钻那笔成为新的最近已还，亦可撤
    assert client.post(f"/api/loans/{la}/unreturn",
                       json={"reason": "误操作"}).status_code == 200


def test_unreturn_active_or_missing_loan_fails(client):
    iid = _add_item(client)
    lid = _lend(client, iid)
    r = client.post(f"/api/loans/{lid}/unreturn", json={"reason": "x"})
    assert r.status_code == 400 and "not_returned" in r.text
    assert client.post("/api/loans/9999/unreturn", json={"reason": "x"}).status_code == 404


def test_unreturn_conflict_fail_keeps_current_state(client):
    iid = _add_item(client)
    a = _lend(client, iid, borrower="甲", due="2099-01-01")
    client.post(f"/api/loans/{a}/return")
    b = _lend(client, iid, borrower="乙", due="2099-02-01")  # 归还后被别人借出

    r = client.post(f"/api/loans/{a}/unreturn",
                    json={"reason": "误点归还", "on_conflict": "fail"})
    assert r.status_code == 409 and "item_relent" in r.text

    item, loan_a = _statuses(client, iid, a)
    _, loan_b = _statuses(client, iid, b)
    assert item == "on_loan"
    assert loan_a["status"] == "returned"
    assert loan_b["status"] == "active"
    board = client.get("/api/board").json()
    assert [l["id"] for l in board["active"]] == [b]


def test_unreturn_conflict_bump_evicts_new_loan(client):
    iid = _add_item(client)
    a = _lend(client, iid, borrower="甲", due="2099-01-01")
    client.post(f"/api/loans/{a}/return")
    b = _lend(client, iid, borrower="乙", due="2099-02-01")

    r = client.post(f"/api/loans/{a}/unreturn",
                    json={"reason": "误点归还", "on_conflict": "bump"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflict"] is True and body["bumped_loan_ids"] == [b]

    item, loan_a = _statuses(client, iid, a)
    _, loan_b = _statuses(client, iid, b)
    assert item == "on_loan"
    assert loan_a["status"] == "active" and loan_a["rev_conflict"] == "bump"
    assert loan_a["returned_at"] is None
    assert loan_b["status"] == "cancelled" and loan_b["rev_conflict"] == "bumped"
    assert "误点归还" in loan_b["unreturn_reason"]

    # 可借栏、在借栏、借还记录跟处置一致：每个 loan id 只落在一个桶
    board = client.get("/api/board").json()
    assert iid not in [i["id"] for i in board["available"]]
    assert [l["id"] for l in board["active"]] == [a]
    rec = client.get("/api/loans").json()
    assert [l["id"] for l in rec["active"]] == [a]
    assert [l["id"] for l in rec["cancelled"]] == [b]
    assert a not in [l["id"] for l in rec["returned"]]
    buckets = rec["active"] + rec["overdue"] + rec["returned"] + rec["cancelled"]
    assert sorted(x["id"] for x in buckets) == sorted([a, b])


def test_relend_after_unreturn_goes_through_mutex(client):
    iid = _add_item(client)
    a = _lend(client, iid, borrower="甲")
    client.post(f"/api/loans/{a}/return")
    assert client.post(f"/api/loans/{a}/unreturn",
                       json={"reason": "误点", "on_conflict": "bump"}).status_code == 200

    # 原笔回到在借：互斥仍生效，直接借出通过必须失败
    r = client.post(f"/api/items/{iid}/lend",
                    json={"borrower": "丙", "due_date": "2099-03-01"})
    assert r.status_code == 409 and "item_not_available" in r.text

    # 原笔再次归还后才能重新借出
    assert client.post(f"/api/loans/{a}/return").status_code == 200
    r = client.post(f"/api/items/{iid}/lend",
                    json={"borrower": "丙", "due_date": "2099-03-01"})
    assert r.status_code == 200
    c = r.json()["loan_id"]
    _, loan_a = _statuses(client, iid, a)
    _, loan_c = _statuses(client, iid, c)
    assert loan_a["status"] == "returned" and loan_c["status"] == "active"


def test_unreturn_overdue_loan_has_single_status_and_row(client):
    # 逾期扫可能已经开始：撤销一笔早已逾期的归还
    iid = _add_item(client)
    lid = _lend(client, iid, due="2020-01-01")
    client.post(f"/api/loans/{lid}/return")
    r = client.post(f"/api/loans/{lid}/unreturn", json={"reason": "逾期单误归还"})
    assert r.status_code == 200

    item, loan = _statuses(client, iid, lid)
    assert item == "on_loan" and loan["status"] == "active"
    rec = client.get("/api/loans").json()
    where = [name for name in ("active", "overdue", "returned", "cancelled")
             if lid in [l["id"] for l in rec[name]]]
    assert where == ["overdue"]  # 只留下一种 items.status 与 loan 行
    board = client.get("/api/board").json()
    assert [l["id"] for l in board["overdue"]] == [lid]
    assert [l["id"] for l in board["active"]] == []
