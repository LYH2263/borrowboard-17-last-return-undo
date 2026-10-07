import os, sqlite3
from contextlib import contextmanager
from pathlib import Path

def db_path() -> Path:
    d = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "borrowboard.db"

def connect():
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    return c

@contextmanager
def write_tx():
    """BEGIN IMMEDIATE 写事务：借出/归还/撤销/逾期扫互斥，
    检查到落库整单原子 —— 只留一种 items.status 与 loan 行。"""
    c = connect()
    c.isolation_level = None
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
