# Stefan – predlog za drugi del

Stefan razvije svoje tri samostojne storitve na veji `stefan-dev`.
Vsaka naj ima svojo bazo, Dockerfile, OpenAPI, CRUD za dve entiteti in HTTP klic druge storitve.

| Storitev | Port | Entiteti za CRUD | Predlagan HTTP klic |
|---|---:|---|---|
| Uporabniki | 8004 | uporabniki, profili | GET Članarine /clanarine?uporabnik_id=ID |
| Termini | 8005 | termini, aktivnosti | GET Ocene /ocene (pozneje filtriranje po termin_id) |
| Rezervacije | 8006 | rezervacije, cakalna-vrsta | GET Uporabniki /uporabniki/ID in GET Termini /termini/ID |

Za vsako entiteto: GET seznam in GET po id, POST na zbirko, PUT in DELETE po id.
V Docker Compose uporabite imena storitev `uporabniki`, `termini`, `rezervacije`.
Za interne klice uporabljajte port 8000 (npr. `http://termini:8000`).

To so predlagani API dogovori, ne implementacija Stefanovega dela.
Trenutno Članarine in Ocene sprejemajo pozitivne zunanje ID-je; ko Stefan
zaključi API, se lahko doda dejansko preverjanje uporabnika in termina preko HTTP.
Ne uporabljajte tujih baz neposredno.
