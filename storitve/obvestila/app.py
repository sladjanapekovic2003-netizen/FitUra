"""Obvestila in nastavitve obveščanja."""
import os
import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)
DB = os.environ["DATABASE_URL"]
GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8080")

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
    return psycopg.connect(DB, row_factory=dict_row, connect_timeout=3)


with connect() as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS obvestila (
          id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, uporabnik_id INTEGER NOT NULL,
          sporocilo TEXT NOT NULL, prebrano BOOLEAN NOT NULL);
        CREATE TABLE IF NOT EXISTS nastavitve (
          id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, uporabnik_id INTEGER NOT NULL UNIQUE,
          email BOOLEAN NOT NULL, push BOOLEAN NOT NULL);
        CREATE INDEX IF NOT EXISTS obvestila_uporabnik_idx ON obvestila(uporabnik_id);
    """)


def serialize(row, table):
    item = dict(row)
    for name, schema in SCHEMAS[table].items():
        if schema["type"] == "boolean":
            item[name] = bool(item[name])
    return item


def error(message, status):
    return jsonify({"error": message}), status


def verify_user(user):
    try:
        response = requests.get(GATEWAY + f"/uporabniki/{user}", timeout=3)
        if response.status_code == 404:
            return error("Uporabnik ne obstaja.", 409)
        response.raise_for_status()
    except requests.RequestException:
        return error("Storitev uporabnikov ni dosegljiva.", 503)
    return None


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
        with connect() as db:
            return jsonify([serialize(r, table) for r in db.execute(f"SELECT * FROM {table} ORDER BY id")])
    data = request.get_json(silent=True)
    if not validate(data, table):
        return error("Neveljavni podatki.", 400)
    verification = verify_user(data["uporabnik_id"])
    if verification:
        return verification
    fields = list(SCHEMAS[table])
    try:
        with connect() as db:
            cursor = db.execute(f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('%s' for _ in fields)}) RETURNING id",
                                tuple(data[f] for f in fields))
            return jsonify({"id": cursor.fetchone()["id"], **data}), 201
    except psycopg.IntegrityError:
        return error("Nastavitve uporabnika že obstajajo.", 409)


def item(table, item_id):
    with connect() as db:
        row = db.execute(f"SELECT * FROM {table} WHERE id=%s", (item_id,)).fetchone()
        if row is None:
            return error("Zapis ne obstaja.", 404)
        if request.method == "GET":
            return jsonify(serialize(row, table))
        if request.method == "DELETE":
            db.execute(f"DELETE FROM {table} WHERE id=%s", (item_id,))
            return "", 204
    data = request.get_json(silent=True)
    if not validate(data, table):
        return error("Neveljavni podatki.", 400)
    verification = verify_user(data["uporabnik_id"])
    if verification:
        return verification
    fields = list(SCHEMAS[table])
    try:
        with connect() as db:
            if not db.execute(f"UPDATE {table} SET {', '.join(f'{f}=%s' for f in fields)} WHERE id=%s",
                              (*[data[f] for f in fields], item_id)).rowcount:
                return error("Zapis ne obstaja.", 404)
    except psycopg.IntegrityError:
        return error("Nastavitve uporabnika že obstajajo.", 409)
    return jsonify({"id": item_id, **data})


for table in SCHEMAS:
    app.add_url_rule(f"/{table}", f"collection_{table}", lambda t=table: collection(t), methods=["GET", "POST"])
    app.add_url_rule(f"/{table}/<int:item_id>", f"item_{table}", lambda item_id, t=table: item(t, item_id), methods=["GET", "PUT", "DELETE"])


@app.get("/health")
def health():
    with connect() as db:
        db.execute("SELECT 1")
    return jsonify({"status": "ok"})


@app.get("/obvestila/uporabnik/<int:user_id>")
def user_notifications(user_id):
    with connect() as db:
        return jsonify([serialize(r, "obvestila") for r in db.execute(
            "SELECT * FROM obvestila WHERE uporabnik_id=%s ORDER BY id", (user_id,))])


@app.get("/uporabniki/<int:user_id>/povzetek")
def summary(user_id):
    with connect() as db:
        count = db.execute("SELECT COUNT(*) AS count FROM obvestila WHERE uporabnik_id=%s AND NOT prebrano", (user_id,)).fetchone()["count"]
    try:
        response = requests.get(GATEWAY + "/clanarina",
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
            "post": {"requestBody": req, "responses": {"201": json_response(result), "400": err, "409": err, "503": err}},
        }
        paths[f"/{table}/{{item_id}}"] = {
            "parameters": param,
            "get": {"responses": {"200": json_response(result), "404": err}},
            "put": {"requestBody": req, "responses": {"200": json_response(result), "400": err, "404": err, "409": err, "503": err}},
            "delete": {"responses": {"204": {"description": "Izbrisano"}, "404": err}},
        }
        if table == "obvestila":
            paths["/obvestila/uporabnik/{user_id}"] = {"get": {
                "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "responses": {"200": json_response({"type": "array", "items": result})}}}
    paths["/health"] = {"get": {"responses": {"200": json_response({"type": "object", "properties": {"status": {"type": "string"}}})}}}
    paths["/uporabniki/{user_id}/povzetek"] = {"get": {
        "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        "responses": {"200": json_response({"type": "object", "properties": {
            "uporabnik_id": {"type": "integer"}, "neprebrana": {"type": "integer"},
            "clanarine": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "integer"}, "uporabnik_id": {"type": "integer"}, "paket_id": {"type": "integer"},
                "zacetek": {"type": "string", "format": "date"}, "konec": {"type": "string", "format": "date"}}}}}}), "503": err}}}
    return jsonify({"openapi": "3.0.3", "info": {"title": "FitUra - Obvestila", "version": "1.0.0"}, "paths": paths})
