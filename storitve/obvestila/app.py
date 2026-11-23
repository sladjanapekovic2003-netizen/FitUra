"""Obvestila in nastavitve obveščanja."""
import os
import sqlite3
from contextlib import closing
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)
DB = os.getenv("DB_PATH", "obvestila.db")

SCHEMAS = {
    "obvestila": {
        "uporabnik_id": {"type": "integer", "minimum": 1},
        "sporocilo": {"type": "string", "minLength": 1, "maxLength": 500},
        "prebrano": {"type": "boolean"},
    },
    "nastavitve": {
        "uporabnik_id": {"type": "integer", "minimum": 1},
        "email": {"type": "boolean"},
        "push": {"type": "boolean"},
    },
}


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


with closing(connect()) as db, db:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS obvestila (
          id INTEGER PRIMARY KEY AUTOINCREMENT, uporabnik_id INTEGER NOT NULL,
          sporocilo TEXT NOT NULL, prebrano INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS nastavitve (
          id INTEGER PRIMARY KEY AUTOINCREMENT, uporabnik_id INTEGER NOT NULL UNIQUE,
          email INTEGER NOT NULL, push INTEGER NOT NULL);
    """)


def serialize(row, table):
    item = dict(row)
    for name, schema in SCHEMAS[table].items():
        if schema["type"] == "boolean":
            item[name] = bool(item[name])
    return item


def error(message, status):
    return jsonify({"error": message}), status


def validate(data, table):
    schema = SCHEMAS[table]
    if not isinstance(data, dict) or set(data) != set(schema):
        return False
    for field, rule in schema.items():
        value = data[field]
        if rule["type"] == "integer" and (type(value) is not int or value < rule["minimum"]):
            return False
        if rule["type"] == "string" and (not isinstance(value, str) or not rule["minLength"] <= len(value) <= rule["maxLength"]):
            return False
        if rule["type"] == "boolean" and type(value) is not bool:
            return False
    return True


def collection(table):
    if request.method == "GET":
        with closing(connect()) as db:
            return jsonify([serialize(r, table) for r in db.execute(f"SELECT * FROM {table} ORDER BY id")])
    data = request.get_json(silent=True)
    if not validate(data, table):
        return error("Neveljavni podatki.", 400)
    fields = list(SCHEMAS[table])
    try:
        with closing(connect()) as db, db:
            cursor = db.execute(f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                                tuple(data[f] for f in fields))
            return jsonify({"id": cursor.lastrowid, **data}), 201
    except sqlite3.IntegrityError:
        return error("Nastavitve uporabnika že obstajajo.", 409)


def item(table, item_id):
    with closing(connect()) as db, db:
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return error("Zapis ne obstaja.", 404)
        if request.method == "GET":
            return jsonify(serialize(row, table))
        if request.method == "DELETE":
            db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            return "", 204
        data = request.get_json(silent=True)
        if not validate(data, table):
            return error("Neveljavni podatki.", 400)
        fields = list(SCHEMAS[table])
        try:
            db.execute(f"UPDATE {table} SET {', '.join(f'{f}=?' for f in fields)} WHERE id=?",
                       (*[data[f] for f in fields], item_id))
        except sqlite3.IntegrityError:
            return error("Nastavitve uporabnika že obstajajo.", 409)
        return jsonify({"id": item_id, **data})


for table in SCHEMAS:
    app.add_url_rule(f"/{table}", f"collection_{table}", lambda t=table: collection(t), methods=["GET", "POST"])
    app.add_url_rule(f"/{table}/<int:item_id>", f"item_{table}", lambda item_id, t=table: item(t, item_id), methods=["GET", "PUT", "DELETE"])


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/uporabniki/<int:user_id>/povzetek")
def summary(user_id):
    with closing(connect()) as db:
        count = db.execute("SELECT COUNT(*) FROM obvestila WHERE uporabnik_id=? AND prebrano=0", (user_id,)).fetchone()[0]
    try:
        response = requests.get(os.getenv("CLANARINE_URL", "http://localhost:8001") + "/clanarine",
                                params={"uporabnik_id": user_id}, timeout=3)
        response.raise_for_status()
        return jsonify({"uporabnik_id": user_id, "neprebrana": count, "clanarine": response.json()})
    except requests.RequestException:
        return error("Storitev članarin ni dosegljiva.", 503)


def json_response(schema, description="Uspeh"):
    return {"description": description, "content": {"application/json": {"schema": schema}}}


@app.get("/openapi.json")
def openapi():
    paths = {}
    err = {"description": "Napaka"}
    for table, properties in SCHEMAS.items():
        body = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
        result = {"type": "object", "properties": {"id": {"type": "integer"}, **properties}, "required": ["id", *properties]}
        req = {"required": True, "content": {"application/json": {"schema": body}}}
        param = [{"name": "item_id", "in": "path", "required": True, "schema": {"type": "integer"}}]
        paths[f"/{table}"] = {
            "get": {"responses": {"200": json_response({"type": "array", "items": result})}},
            "post": {"requestBody": req, "responses": {"201": json_response(result), "400": err, **({"409": err} if table == "nastavitve" else {})}},
        }
        paths[f"/{table}/{{item_id}}"] = {
            "parameters": param,
            "get": {"responses": {"200": json_response(result), "404": err}},
            "put": {"requestBody": req, "responses": {"200": json_response(result), "400": err, "404": err, **({"409": err} if table == "nastavitve" else {})}},
            "delete": {"responses": {"204": {"description": "Izbrisano"}, "404": err}},
        }
    paths["/health"] = {"get": {"responses": {"200": json_response({"type": "object", "properties": {"status": {"type": "string"}}})}}}
    paths["/uporabniki/{user_id}/povzetek"] = {"get": {
        "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        "responses": {"200": json_response({"type": "object", "properties": {
            "uporabnik_id": {"type": "integer"}, "neprebrana": {"type": "integer"},
            "clanarine": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "integer"}, "uporabnik_id": {"type": "integer"}, "paket_id": {"type": "integer"},
                "zacetek": {"type": "string", "format": "date"}, "konec": {"type": "string", "format": "date"}}}}}}), "503": err}}}
    return jsonify({"openapi": "3.0.3", "info": {"title": "FitUra - Obvestila", "version": "1.0.0"}, "paths": paths})
