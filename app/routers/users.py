"""Users: list + create (multi-user capable; any user can create trips/catches)."""
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..models import UserIn, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@router.get("", response_model=list[UserOut])
def list_users(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute("SELECT id, name, email FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserIn, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)", (body.name, body.email)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"user '{body.name}' already exists")
    row = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)
