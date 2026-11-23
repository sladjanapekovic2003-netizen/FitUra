"""Članarine in paketi članarin."""
import os
import sqlite3
from contextlib import closing
from datetime import date
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

app = FastAPI(title="FitUra - Članarine", version="1.0.0")
DB = os.getenv("DB_PATH", "clanarine.db")


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


with closing(connect()) as db, db:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS paketi (
          id INTEGER PRIMARY KEY AUTOINCREMENT, naziv TEXT NOT NULL,
          cena_centov INTEGER NOT NULL CHECK(cena_centov >= 0));
        CREATE TABLE IF NOT EXISTS clanarine (
          id INTEGER PRIMARY KEY AUTOINCREMENT, uporabnik_id INTEGER NOT NULL,
          paket_id INTEGER NOT NULL REFERENCES paketi(id),
          zacetek TEXT NOT NULL, konec TEXT NOT NULL);
    """)


class Paket(BaseModel):
    naziv: str = Field(min_length=1, max_length=100)
    cena_centov: int = Field(ge=0)


class Clanarina(BaseModel):
    uporabnik_id: int = Field(gt=0)
    paket_id: int = Field(gt=0)
    zacetek: date
    konec: date

    @model_validator(mode="after")
    def dates(self):
        if self.konec < self.zacetek:
            raise ValueError("Konec ne sme biti pred začetkom.")
        return self


class PaketOut(Paket):
    id: int


class ClanarinaOut(Clanarina):
    id: int


class ClanarinaCreated(ClanarinaOut):
    obvestilo_poslano: bool


def list_rows(table, user=None):
    with closing(connect()) as db:
        if user is not None:
            return [dict(r) for r in db.execute(
                f"SELECT * FROM {table} WHERE uporabnik_id=? ORDER BY id", (user,))]
        return [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY id")]


def get_row(table, item_id):
    with closing(connect()) as db:
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Zapis ne obstaja.")
    return dict(row)


def save(table, data, item_id=None):
    fields = list(data)
    try:
        with closing(connect()) as db, db:
            if item_id is None:
                marks = ", ".join("?" for _ in fields)
                cursor = db.execute(
                    f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({marks})",
                    tuple(data.values()))
                item_id = cursor.lastrowid
            else:
                assignments = ", ".join(f"{f}=?" for f in fields)
                cursor = db.execute(f"UPDATE {table} SET {assignments} WHERE id=?",
                                    (*data.values(), item_id))
                if not cursor.rowcount:
                    raise HTTPException(404, "Zapis ne obstaja.")
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Neveljaven sklic na paket.") from exc
    return get_row(table, item_id)


def remove(table, item_id):
    try:
        with closing(connect()) as db, db:
            if not db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,)).rowcount:
                raise HTTPException(404, "Zapis ne obstaja.")
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Paket je v uporabi.") from exc


def notify(user):
    try:
        response = httpx.post(
            os.getenv("OBVESTILA_URL", "http://localhost:8002") + "/obvestila",
            json={"uporabnik_id": user, "sporocilo": "Članarina je ustvarjena.", "prebrano": False},
            timeout=3)
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/paketi", response_model=list[PaketOut])
def paketi():
    return list_rows("paketi")


@app.get("/paketi/{item_id}", response_model=PaketOut, responses={404: {"description": "Ni zapisa"}})
def paket(item_id: int):
    return get_row("paketi", item_id)


@app.post("/paketi", response_model=PaketOut, status_code=201)
def create_paket(body: Paket):
    return save("paketi", body.model_dump())


@app.put("/paketi/{item_id}", response_model=PaketOut, responses={404: {"description": "Ni zapisa"}})
def update_paket(item_id: int, body: Paket):
    return save("paketi", body.model_dump(), item_id)


@app.delete("/paketi/{item_id}", status_code=204, responses={404: {"description": "Ni zapisa"}, 409: {"description": "Paket v uporabi"}})
def delete_paket(item_id: int):
    remove("paketi", item_id)


@app.get("/clanarine", response_model=list[ClanarinaOut])
def clanarine(uporabnik_id: int | None = None):
    return list_rows("clanarine", uporabnik_id)


@app.get("/clanarine/{item_id}", response_model=ClanarinaOut, responses={404: {"description": "Ni zapisa"}})
def clanarina(item_id: int):
    return get_row("clanarine", item_id)


@app.post("/clanarine", response_model=ClanarinaCreated, status_code=201, responses={409: {"description": "Neveljaven paket"}})
def create_clanarina(body: Clanarina):
    row = save("clanarine", body.model_dump(mode="json"))
    return {**row, "obvestilo_poslano": notify(body.uporabnik_id)}


@app.put("/clanarine/{item_id}", response_model=ClanarinaOut, responses={404: {"description": "Ni zapisa"}, 409: {"description": "Neveljaven paket"}})
def update_clanarina(item_id: int, body: Clanarina):
    return save("clanarine", body.model_dump(mode="json"), item_id)


@app.delete("/clanarine/{item_id}", status_code=204, responses={404: {"description": "Ni zapisa"}})
def delete_clanarina(item_id: int):
    remove("clanarine", item_id)
