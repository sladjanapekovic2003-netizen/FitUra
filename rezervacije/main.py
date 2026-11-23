import os
from contextlib import contextmanager
from datetime import datetime
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from psycopg2 import pool, IntegrityError
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="FitUra - Rezervacije", version="1.0.0")

TERMINI_URL = os.getenv("TERMINI_URL", "http://localhost:3002")
OBVESTILA_URL = os.getenv("OBVESTILA_URL", "http://localhost:8002")
UPORABNIKI_URL = os.getenv("UPORABNIKI_URL", "http://localhost:3001")

# Connection pool - dobra praksa, ne odpiramo nove konekcije za vsak zahtevek
bazen = pool.ThreadedConnectionPool(
    1, 10,
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", "postgres"),
    dbname=os.getenv("DB_NAME", "rezervacije_db"),
)


@contextmanager
def dobi_kurzor():
    konekcija = bazen.getconn()
    try:
        with konekcija.cursor() as kurzor:
            yield kurzor
        konekcija.commit()
    except Exception:
        konekcija.rollback()
        raise
    finally:
        bazen.putconn(konekcija)


class RezervacijaVnos(BaseModel):
    uporabnik_id: int = Field(gt=0)
    termin_id: int = Field(gt=0)


class StatusVnos(BaseModel):
    status: Literal["aktivna", "potrjena", "odpovedana"]


def vrstica_v_slovar(vrstica):
    return {
        "id": vrstica[0],
        "uporabnik_id": vrstica[1],
        "termin_id": vrstica[2],
        "datum_rezervacije": vrstica[3],
        "status": vrstica[4],
        "obvestilo_poslano": vrstica[5],
    }


def preveri_termin(termin_id: int):
    try:
        odgovor = httpx.get(f"{TERMINI_URL}/termini/{termin_id}", timeout=3)
    except httpx.RequestError:
        raise HTTPException(503, "Storitev Termini ni dosegljiva.")
    if odgovor.status_code == 404:
        raise HTTPException(404, "Termin ne obstaja.")
    if not odgovor.is_success:
        raise HTTPException(503, "Storitev Termini ni dosegljiva.")
    podatki = odgovor.json()
    if not podatki.get("aktiven", True):
        raise HTTPException(409, "Termin je odpovedan.")


def preveri_uporabnika(uporabnik_id: int):
    try:
        odgovor = httpx.get(f"{UPORABNIKI_URL}/uporabniki/{uporabnik_id}", timeout=3)
    except httpx.RequestError:
        raise HTTPException(503, "Storitev Uporabniki ni dosegljiva.")
    if odgovor.status_code == 404:
        raise HTTPException(409, "Uporabnik ne obstaja.")
    if not odgovor.is_success:
        raise HTTPException(503, "Storitev Uporabniki ni dosegljiva.")


def posredi_obvestilo(uporabnik_id: int, sporocilo: str) -> bool:
    try:
        odgovor = httpx.post(
            f"{OBVESTILA_URL}/obvestila",
            json={"uporabnik_id": uporabnik_id, "sporocilo": sporocilo, "prebrano": False},
            timeout=3,
        )
        return odgovor.status_code < 300
    except httpx.RequestError:
        return False


@app.get("/health")
def health():
    with dobi_kurzor() as kurzor:
        kurzor.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/rezervacije")
def seznam_rezervacij():
    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "SELECT id, uporabnik_id, termin_id, datum_rezervacije, status, obvestilo_poslano "
            "FROM rezervacije ORDER BY id"
        )
        return [vrstica_v_slovar(v) for v in kurzor.fetchall()]


@app.get("/rezervacije/uporabnik/{uporabnik_id}")
def rezervacije_uporabnika(uporabnik_id: int):
    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "SELECT id, uporabnik_id, termin_id, datum_rezervacije, status, obvestilo_poslano "
            "FROM rezervacije WHERE uporabnik_id = %s ORDER BY id",
            (uporabnik_id,),
        )
        return [vrstica_v_slovar(v) for v in kurzor.fetchall()]


@app.get("/rezervacije/{rezervacija_id}")
def ena_rezervacija(rezervacija_id: int):
    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "SELECT id, uporabnik_id, termin_id, datum_rezervacije, status, obvestilo_poslano "
            "FROM rezervacije WHERE id = %s",
            (rezervacija_id,),
        )
        vrstica = kurzor.fetchone()
    if vrstica is None:
        raise HTTPException(404, "Rezervacija ne obstaja.")
    return vrstica_v_slovar(vrstica)


@app.post("/rezervacije", status_code=201, responses={404: {"description": "Termin ne obstaja"}, 409: {"description": "Neveljaven uporabnik ali odpovedan termin"}, 503: {"description": "Odvisna storitev ni dosegljiva"}})
def nova_rezervacija(vnos: RezervacijaVnos):
    preveri_termin(vnos.termin_id)
    preveri_uporabnika(vnos.uporabnik_id)

    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "INSERT INTO rezervacije (uporabnik_id, termin_id) VALUES (%s, %s) "
            "RETURNING id, uporabnik_id, termin_id, datum_rezervacije, status, obvestilo_poslano",
            (vnos.uporabnik_id, vnos.termin_id),
        )
        vrstica = kurzor.fetchone()

    obvestilo_poslano = posredi_obvestilo(vnos.uporabnik_id, "Rezervacija je ustvarjena.")
    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "UPDATE rezervacije SET obvestilo_poslano = %s WHERE id = %s",
            (obvestilo_poslano, vrstica[0]),
        )

    rezultat = vrstica_v_slovar(vrstica)
    rezultat["obvestilo_poslano"] = obvestilo_poslano
    return rezultat


@app.post("/rezervacije/{rezervacija_id}/potvrdi")
def potrdi_rezervacijo(rezervacija_id: int):
    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "UPDATE rezervacije SET status = 'potrjena' WHERE id = %s RETURNING id",
            (rezervacija_id,),
        )
        if kurzor.fetchone() is None:
            raise HTTPException(404, "Rezervacija ne obstaja.")
    return {"sporocilo": "Rezervacija potrjena."}


@app.put("/rezervacije/{rezervacija_id}", responses={404: {"description": "Rezervacija ali termin ne obstaja"}, 409: {"description": "Neveljaven uporabnik ali odpovedan termin"}, 503: {"description": "Odvisna storitev ni dosegljiva"}})
def uredi_rezervacijo(rezervacija_id: int, vnos: RezervacijaVnos):
    preveri_termin(vnos.termin_id)
    preveri_uporabnika(vnos.uporabnik_id)
    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "UPDATE rezervacije SET uporabnik_id = %s, termin_id = %s WHERE id = %s RETURNING id",
            (vnos.uporabnik_id, vnos.termin_id, rezervacija_id),
        )
        if kurzor.fetchone() is None:
            raise HTTPException(404, "Rezervacija ne obstaja.")
    return {"sporocilo": "Rezervacija posodobljena."}


@app.put("/rezervacije/{rezervacija_id}/status")
def spremeni_status(rezervacija_id: int, vnos: StatusVnos):
    with dobi_kurzor() as kurzor:
        kurzor.execute(
            "UPDATE rezervacije SET status = %s WHERE id = %s RETURNING id",
            (vnos.status, rezervacija_id),
        )
        if kurzor.fetchone() is None:
            raise HTTPException(404, "Rezervacija ne obstaja.")
    return {"sporocilo": "Status posodobljen."}


@app.delete("/rezervacije/{rezervacija_id}")
def izbrisi_rezervacijo(rezervacija_id: int):
    with dobi_kurzor() as kurzor:
        kurzor.execute("DELETE FROM rezervacije WHERE id = %s RETURNING id", (rezervacija_id,))
        if kurzor.fetchone() is None:
            raise HTTPException(404, "Rezervacija ne obstaja.")
    return {"sporocilo": "Rezervacija izbrisana."}


@app.delete("/rezervacije")
def izbrisi_vse():
    with dobi_kurzor() as kurzor:
        kurzor.execute("DELETE FROM rezervacije")
    return {"sporocilo": "Vse rezervacije izbrisane."}
