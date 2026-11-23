"""Integration tests against all six real services through the API Gateway."""
import json
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = {name: f"http://localhost:{port}" for name, port in [
    ("clanarine", 8001), ("obvestila", 8002), ("ocene", 8003),
    ("uporabniki", 3001), ("termini", 3002), ("rezervacije", 3003)]}


def call(service, method, path, data=None, expected=200):
    base = "http://localhost:8080" if service == "gateway" else BASE[service]
    req = Request(base + path, method=method,
                  data=None if data is None else json.dumps(data).encode(),
                  headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=15)
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
            for _ in range(60):
                try:
                    call(service, "GET", "/health")
                    break
                except (URLError, OSError, AssertionError):
                    time.sleep(1)
            else:
                raise RuntimeError(f"{service} is not ready")

    def test_openapi(self):
        root = Path(__file__).resolve().parents[1]
        for service in BASE:
            with self.subTest(service=service):
                spec = call(service, "GET", "/openapi.json")
                folder = root / "storitve" / service if service in ("clanarine", "obvestila", "ocene") else root / service
                exported = folder / "openapi.json"
                if exported.exists():
                    self.assertEqual(spec, json.loads(exported.read_text(encoding="utf-8")))
                for method in ("get", "post", "put", "delete"):
                    count = sum(method in ops for path, ops in spec["paths"].items() if path != "/health")
                    self.assertGreaterEqual(count, 2, (service, method))
        required = {
            "clanarine": "/clanarina/{item_id}",
            "obvestila": "/obvestila/uporabnik/{user_id}",
            "ocene": "/ocene/trener/{id}",
            "rezervacije": "/rezervacije/uporabnik/{uporabnik_id}",
        }
        for service, path in required.items():
            self.assertIn(path, call(service, "GET", "/openapi.json")["paths"])

    def request(self, method, path, data=None, expected=200):
        return call("gateway", method, path, data, expected)

    def create(self, path, data, delete_path=None, delete_status=204):
        row = self.request("POST", path, data, 201)
        self.addCleanup(self.request, "DELETE", (delete_path or path) + "/" + str(row["id"]), expected=delete_status)
        return row

    def test_real_end_to_end(self):
        """Create a user, term, membership, reservation and review; verify all six links."""
        unique = str(time.time_ns())
        user = self.create("/registracija", {"ime": "Integration Test", "email": f"test{unique}@example.test",
                            "geslo": "LocalTest123!"}, "/uporabniki", delete_status=200)
        uid = user["id"]
        self.assertEqual(self.request("POST", "/prijava", {"email": user["email"], "geslo": "LocalTest123!"})["id"], uid)
        self.assertEqual(self.request("GET", f"/uporabniki/{uid}")["id"], uid)
        self.assertEqual(self.request("GET", f"/uporabnik/{uid}")["id"], uid)
        self.request("PUT", f"/uporabniki/{uid}", {"ime": "Integration Updated"})
        self.request("PUT", f"/uporabniki/{uid}/geslo", {"staro_geslo": "LocalTest123!", "novo_geslo": "LocalTest456!"})
        self.assertEqual(self.request("POST", "/prijava", {"email": user["email"], "geslo": "LocalTest456!"})["id"], uid)

        term_body = {"naziv": "Integration Test", "tip": "Vadba", "trener": "Test trener",
                     "datumCas": "2027-01-15T10:00:00", "kapaciteta": 12}
        term = self.create("/termini", term_body, delete_status=200)
        tid = term["id"]
        trainer = self.request("GET", f"/termini/{tid}")["trener_id"]
        self.assertGreater(trainer, 0)
        duplicate = self.request("POST", f"/termini/{tid}/podvoji", expected=201)
        self.addCleanup(self.request, "DELETE", f"/termini/{duplicate['id']}")
        self.assertEqual(duplicate["trener_id"], trainer)
        self.request("PUT", f"/termini/{tid}", {**term_body, "kapaciteta": 15})
        self.request("PUT", f"/termini/{tid}/status", {"aktiven": True})
        self.assertEqual(self.request("GET", f"/termini/{tid}")["trener_id"], trainer)

        previous_notifications = {n["id"] for n in self.request("GET", f"/obvestila/uporabnik/{uid}")}

        def cleanup_notifications():
            for row in self.request("GET", f"/obvestila/uporabnik/{uid}"):
                if row["id"] not in previous_notifications:
                    self.request("DELETE", f"/obvestila/{row['id']}", expected=204)

        self.addCleanup(cleanup_notifications)
        package = self.create("/paketi", {"naziv": "Test", "cena_centov": 2999})
        self.request("PUT", f"/paketi/{package['id']}", {"naziv": "Updated", "cena_centov": 3999})
        self.assertEqual(self.request("GET", f"/paketi/{package['id']}")["cena_centov"], 3999)
        membership_body = {"uporabnik_id": uid, "paket_id": package["id"], "zacetek": "2027-01-01", "konec": "2027-02-01"}
        membership = self.create("/clanarina", membership_body)
        self.assertTrue(membership["obvestilo_poslano"])
        self.request("PUT", f"/clanarina/{membership['id']}", {**membership_body, "konec": "2027-03-01"})
        self.assertIn(membership["id"], [m["id"] for m in self.request("GET", f"/uporabniki/{uid}/clanarstvo")])
        self.assertEqual(self.request("GET", f"/clanarina/{membership['id']}")["konec"], "2027-03-01")
        self.request("DELETE", f"/paketi/{package['id']}", expected=409)

        data = {"uporabnik_id": uid, "termin_id": tid}
        reservation = self.request("POST", "/rezervacije", data, 201)
        rid = reservation["id"]
        self.addCleanup(self.request, "DELETE", f"/rezervacije/{rid}")
        self.assertTrue(reservation["obvestilo_poslano"])
        self.request("POST", f"/rezervacije/{rid}/potvrdi")
        self.request("PUT", f"/rezervacije/{rid}", data)
        self.request("PUT", f"/rezervacije/{rid}/status", {"status": "potrjena"})
        self.assertIn(rid, [r["id"] for r in self.request("GET", f"/rezervacije/uporabnik/{uid}")])
        self.assertEqual(self.request("GET", f"/rezervacije/{rid}")["status"], "potrjena")
        self.request("POST", "/rezervacije", {**data, "uporabnik_id": 2147483647}, 409)
        self.request("POST", "/rezervacije", {**data, "termin_id": 2147483647}, 404)

        review_body = {**data, "ocena": 4, "komentar": "Super"}
        review = self.create("/ocene", review_body)
        self.assertTrue(review["obvestilo_poslano"])
        self.assertEqual(review["trener_id"], trainer)
        self.request("PUT", f"/ocene/{review['id']}", {**review_body, "ocena": 5})
        self.assertIn(review["id"], [r["id"] for r in self.request("GET", f"/termini/{tid}/ocena")])
        self.assertIn(review["id"], [r["id"] for r in self.request("GET", f"/ocene/trener/{trainer}")])
        self.request("POST", "/ocene", {**review_body, "trener_id": 2147483647}, 409)
        reply = self.create("/odgovori", {"ocena_id": review["id"], "besedilo": "Hvala"})
        self.request("PUT", f"/odgovori/{reply['id']}", {"ocena_id": review["id"], "besedilo": "Najlepša hvala"})
        self.assertEqual(self.request("GET", f"/odgovori/{reply['id']}")["besedilo"], "Najlepša hvala")
        self.request("DELETE", f"/ocene/{review['id']}", expected=409)

        messages = [n for n in self.request("GET", f"/obvestila/uporabnik/{uid}") if n["id"] not in previous_notifications]
        self.assertEqual(len(messages), 3)
        self.assertIn("Rezervacija je ustvarjena.", [n["sporocilo"] for n in messages])
        summary = self.request("GET", f"/uporabniki/{uid}/povzetek")
        self.assertIn(membership["id"], [m["id"] for m in summary["clanarine"]])
        for n in messages:
            self.request("PUT", f"/obvestila/{n['id']}", {"uporabnik_id": uid, "sporocilo": n["sporocilo"], "prebrano": True})
            self.assertTrue(self.request("GET", f"/obvestila/{n['id']}")["prebrano"])
        if not any(row["uporabnik_id"] == uid for row in self.request("GET", "/nastavitve")):
            settings = self.create("/nastavitve", {"uporabnik_id": uid, "email": True, "push": False})
            self.request("PUT", f"/nastavitve/{settings['id']}", {"uporabnik_id": uid, "email": False, "push": True})
            self.assertTrue(self.request("GET", f"/nastavitve/{settings['id']}")["push"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
