"""Run against the three live Docker services (stdlib only)."""
import json
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = {name: f"http://localhost:{port}" for name, port in
        [("clanarine", 8001), ("obvestila", 8002), ("ocene", 8003)]}


def call(service, method, path, data=None, expected=200):
    req = Request(BASE[service] + path, method=method,
                  data=None if data is None else json.dumps(data).encode(),
                  headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read()
        assert response.status == expected, (service, method, path, response.status, body)
        return json.loads(body) if body else None


class FitUraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for service in BASE:
            for _ in range(30):
                try:
                    call(service, "GET", "/health")
                    break
                except (URLError, OSError, AssertionError):
                    time.sleep(1)
            else:
                raise RuntimeError(f"{service} is not ready")

    def test_openapi(self):
        for service in BASE:
            spec = call(service, "GET", "/openapi.json")
            exported = Path(__file__).resolve().parents[1] / "storitve" / service / "openapi.json"
            if exported.exists():
                self.assertEqual(spec, json.loads(exported.read_text(encoding="utf-8")))
            for method in ("get", "post", "put", "delete"):
                count = sum(method in path for path in spec["paths"].values())
                self.assertGreaterEqual(count, 2, (service, method))

    def crud(self, service, resource, data, update):
        created = call(service, "POST", resource, data, 201)
        item = resource + "/" + str(created["id"])
        self.assertIn(created["id"], [r["id"] for r in call(service, "GET", resource)])
        self.assertEqual(call(service, "GET", item)["id"], created["id"])
        updated = call(service, "PUT", item, update)
        for key, value in update.items():
            self.assertEqual(updated[key], value)
        call(service, "DELETE", item, expected=204)
        call(service, "GET", item, expected=404)
        return created

    def test_clanarine_and_notification(self):
        user = time.time_ns() % 2000000000 + 1
        self.crud("clanarine", "/paketi", {"naziv": "Mesecni", "cena_centov": 2900},
                  {"naziv": "Letni", "cena_centov": 20000})
        package = call("clanarine", "POST", "/paketi", {"naziv": "Test", "cena_centov": 100}, 201)
        package_path = "/paketi/" + str(package["id"])
        body = {"uporabnik_id": user, "paket_id": package["id"], "zacetek": "2026-01-01", "konec": "2026-02-01"}
        try:
            membership = self.crud("clanarine", "/clanarine", body, {**body, "konec": "2026-03-01"})
            self.assertTrue(membership["obvestilo_poslano"])
            call("clanarine", "POST", "/clanarine", {**body, "konec": "2025-01-01"}, 422)
            notifications = call("obvestila", "GET", "/obvestila")
            matching = [n for n in notifications if n["uporabnik_id"] == user]
            self.assertTrue(matching)
            for n in matching:
                call("obvestila", "DELETE", "/obvestila/" + str(n["id"]), expected=204)
        finally:
            call("clanarine", "DELETE", package_path, expected=204)

    def test_obvestila_and_membership_summary(self):
        user = time.time_ns() % 2000000000 + 1
        data = {"uporabnik_id": user, "sporocilo": "Test", "prebrano": False}
        self.crud("obvestila", "/obvestila", data, {**data, "prebrano": True})
        settings = {"uporabnik_id": user, "email": True, "push": False}
        self.crud("obvestila", "/nastavitve", settings, {**settings, "push": True})
        call("obvestila", "POST", "/obvestila", {**data, "prebrano": "true"}, 400)
        package = call("clanarine", "POST", "/paketi", {"naziv": "Povzetek", "cena_centov": 100}, 201)
        membership = call("clanarine", "POST", "/clanarine", {
            "uporabnik_id": user, "paket_id": package["id"], "zacetek": "2026-01-01", "konec": "2026-02-01"}, 201)
        summary = call("obvestila", "GET", f"/uporabniki/{user}/povzetek")
        self.assertEqual(summary["neprebrana"], 1)
        self.assertEqual(summary["clanarine"][0]["id"], membership["id"])
        call("clanarine", "DELETE", "/paketi/" + str(package["id"]), expected=409)
        call("clanarine", "DELETE", "/clanarine/" + str(membership["id"]), expected=204)
        call("clanarine", "DELETE", "/paketi/" + str(package["id"]), expected=204)
        for n in call("obvestila", "GET", "/obvestila"):
            if n["uporabnik_id"] == user:
                call("obvestila", "DELETE", "/obvestila/" + str(n["id"]), expected=204)

    def test_ocene_and_notification(self):
        user = time.time_ns() % 2000000000 + 1
        body = {"uporabnik_id": user, "termin_id": 1, "ocena": 4, "komentar": "Super"}
        review = self.crud("ocene", "/ocene", body, {**body, "ocena": 5})
        self.assertTrue(review["obvestilo_poslano"])
        existing = call("ocene", "POST", "/ocene", body, 201)
        reply = {"ocena_id": existing["id"], "besedilo": "Hvala"}
        self.crud("ocene", "/odgovori", reply, {**reply, "besedilo": "Najlepša hvala"})
        call("ocene", "POST", "/ocene", {**body, "ocena": 10}, 400)
        call("ocene", "DELETE", "/ocene/" + str(existing["id"]), expected=204)
        matching = [n for n in call("obvestila", "GET", "/obvestila") if n["uporabnik_id"] == user]
        self.assertEqual(len(matching), 2)
        for n in matching:
            call("obvestila", "DELETE", "/obvestila/" + str(n["id"]), expected=204)


if __name__ == "__main__":
    unittest.main(verbosity=2)
