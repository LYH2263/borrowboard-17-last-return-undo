from app.db import connect

# 撤销归还需要的 loans 列；旧库走 ALTER 迁移
LOAN_UNDO_COLS = [
    ("undo_reason", "ALTER TABLE loans ADD COLUMN undo_reason TEXT"),
    ("undo_disposition", "ALTER TABLE loans ADD COLUMN undo_disposition TEXT"),
    ("undone_at", "ALTER TABLE loans ADD COLUMN undone_at TEXT"),
    ("bumped_by", "ALTER TABLE loans ADD COLUMN bumped_by INT"),
]

def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS items(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, owner TEXT, status TEXT, data_quality TEXT
    );
    CREATE TABLE IF NOT EXISTS loans(
      id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INT, borrower TEXT, status TEXT,
      due_date TEXT, lent_at TEXT, returned_at TEXT,
      undo_reason TEXT, undo_disposition TEXT, undone_at TEXT, bumped_by INT
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(loans)")}
    for name, ddl in LOAN_UNDO_COLS:
        if name not in cols:
            c.execute(ddl)
    c.commit()
    if c.execute("SELECT COUNT(*) c FROM items").fetchone()["c"] == 0:
        c.executemany("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)", [
            ("电钻", "老周", "available", "clean"),
            ("折叠桌", "小陈", "available", "clean"),
            ("脏数据-无主", "", "available", "dirty"),
            ("已外借样例", "阿强", "on_loan", "clean"),
        ])
        c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (4, "邻居甲", "active", "2020-06-01", "2020-05-01"),
        )
        c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at,returned_at) VALUES (?,?,?,?,?,?)",
            (1, "邻居乙", "returned", "2026-12-31", "2026-09-20", "2026-09-25"),
        )
        c.execute("INSERT INTO settings(key,value) VALUES ('board_name','木色邻里板')")
        c.commit()
    c.close()
