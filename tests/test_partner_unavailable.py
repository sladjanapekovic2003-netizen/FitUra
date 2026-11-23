"""Run with the real partner services and test double stopped."""
from test_api import call


def main():
    package = call("clanarine", "POST", "/paketi", {"naziv": "Unavailable test", "cena_centov": 100}, 201)
    try:
        membership = {"uporabnik_id": 1, "paket_id": package["id"], "zacetek": "2026-01-01", "konec": "2026-02-01"}
        call("clanarine", "POST", "/clanarina", membership, 503)
        call("obvestila", "POST", "/obvestila", {"uporabnik_id": 1, "sporocilo": "test", "prebrano": False}, 503)
        call("ocene", "POST", "/ocene", {"uporabnik_id": 1, "termin_id": 1, "ocena": 5, "komentar": "test"}, 503)
        assert not any(row["paket_id"] == package["id"] for row in call("clanarine", "GET", "/clanarina"))
        print("All three services return 503 when their required partner is unavailable.")
    finally:
        call("clanarine", "DELETE", "/paketi/" + str(package["id"]), expected=204)


if __name__ == "__main__":
    main()
