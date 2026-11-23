# FitUra – prva naloga

Mikrostoritvena spletna aplikacija za rezervacijo terminov v fitnes centru.
Ekipa: Sladjana in Stefan (Ssqured).

## Razdelitev dela

| Lastnik | Mikrostoritev | Framework | Lokalni port | Status |
|---|---|---|---:|---|
| Sladjana | Članarine | Python / FastAPI | 8001 | Implementirano |
| Sladjana | Obvestila | Python / Flask | 8002 | Implementirano |
| Sladjana | Ocene | Node.js / Express | 8003 | Implementirano |
| Stefan | Uporabniki | Stefanova izbira | 8004 | Načrt |
| Stefan | Termini | Stefanova izbira | 8005 | Načrt |
| Stefan | Rezervacije | Stefanova izbira | 8006 | Načrt |

Vsaka implementirana storitev ima svojo SQLite bazo in Docker volume.
Podatkovne baze si ne delijo; komunikacija med storitvami je HTTP.
Uporabljeni so trije različni spletni frameworki.

## Zagon

Potrebujete Git, Docker Desktop, Python 3 (za integracijske teste) in po želji VS Code.
V terminalu v korenu projekta:

```sh
docker compose up --build -d
docker compose ps
python3 tests/test_api.py
```

Prvi zagon lahko traja več minut zaradi prenosa slik. Docker Desktop mora biti vklopljen.
Za ustavitev brez brisanja podatkov uporabite `docker compose down`.

| Storitev | Health | OpenAPI |
|---|---|---|
| Članarine | http://localhost:8001/health | http://localhost:8001/docs |
| Obvestila | http://localhost:8002/health | http://localhost:8002/openapi.json |
| Ocene | http://localhost:8003/health | http://localhost:8003/openapi.json |

FastAPI ima vgrajen Swagger UI. Za Flask in Express uvozite njuno datoteko
`openapi.json` v Postman oziroma odprite specifikacijo v urejevalniku Swagger.
Po spremembi API-ja obnovite datoteke specifikacij z:

```sh
python3 tests/export_openapi.py
```

## REST operacije

Za vsak spodnji par entitet je na voljo vseh pet operacij:

| Metoda | Pot | Namen |
|---|---|---|
| GET | /entiteta | Seznam |
| GET | /entiteta/{id} | En zapis |
| POST | /entiteta | Ustvari zapis |
| PUT | /entiteta/{id} | Posodobi celoten zapis (vsa polja) |
| DELETE | /entiteta/{id} | Izbriši zapis |

| Mikrostoritev | Entiteta 1 | Entiteta 2 | GET | POST | PUT | DELETE |
|---|---|---|---:|---:|---:|---:|
| Članarine | /paketi | /clanarine | 4 | 2 | 2 | 2 |
| Obvestila | /obvestila | /nastavitve | 5 | 2 | 2 | 2 |
| Ocene | /ocene | /odgovori | 4 | 2 | 2 | 2 |

Število GET ne vključuje tehničnih poti /health in /openapi.json.
Statusi: 200 (uspeh), 201 (ustvarjeno), 204 (izbrisano),
400 ali 422 (neveljavni podatki), 404 (ni zapisa), 409 (konflikt).

## Medsebojna komunikacija

- Članarine → Obvestila: POST /obvestila pri ustvarjanju članarine.
- Ocene → Obvestila: POST /obvestila pri ustvarjanju ocene.
- Obvestila → Članarine: GET /clanarine?uporabnik_id=ID za povzetek na
  GET /uporabniki/{user_id}/povzetek.

Članarina/ocena je shranjena tudi, če je storitev za obvestila nedosegljiva.
Polje `obvestilo_poslano` pove, ali je obvestilo uspešno ustvarjeno.
Povzetek vrne 503, če storitev Članarine ni dosegljiva.
Gre za notranja obvestila v aplikaciji, ne za dejansko pošiljanje e-pošte/SMS.

## Ročni primer (Swagger UI ali terminal)

Najprej ustvarite paket in si zapišite njegov dejanski ID:

```sh
curl -X POST http://localhost:8001/paketi \
  -H 'Content-Type: application/json' \
  -d '{"naziv":"Mesecni","cena_centov":2999}'
```

Če odgovor vrne ID 1, ustvarite članarino (sicer vnesite vrnjeni ID):

```sh
curl -X POST http://localhost:8001/clanarine \
  -H 'Content-Type: application/json' \
  -d '{"uporabnik_id":1,"paket_id":1,"zacetek":"2026-11-23","konec":"2026-12-23"}'
curl http://localhost:8002/obvestila
curl http://localhost:8002/uporabniki/1/povzetek
```

Nato ustvarite oceno:

```sh
curl -X POST http://localhost:8003/ocene \
  -H 'Content-Type: application/json' \
  -d '{"uporabnik_id":1,"termin_id":1,"ocena":5,"komentar":"Odlicno"}'
curl http://localhost:8002/obvestila
```

## Datotečna struktura

```text
FitUra/
├── compose.yaml
├── README.md
├── docs/stefan.md
├── storitve/
│   ├── clanarine/  (app.py, requirements.txt, Dockerfile, openapi.json)
│   ├── obvestila/  (app.py, requirements.txt, Dockerfile, openapi.json)
│   └── ocene/      (app.js, package.json, package-lock.json, Dockerfile, openapi.json)
└── tests/
    ├── test_api.py
    └── export_openapi.py
```

## Dobre prakse in meje prve naloge

Ločene baze in volumni, parametri SQL, validacija vhodov, HTTP časovne omejitve,
smiselne statusne kode, brez gesel v kodi, verzionirane glavne knjižnice,
OpenAPI in integracijski testi. Baze vsebujejo samo lokalne razvojne podatke.
Uporabniki in termini so trenutno zunanji ID-ji, brez preverjanja pri Stefanu.
Prva naloga še ne vključuje prijave, avtorizacije, dejanskega plačevanja, frontenda
ali varne produkcijske namestitve. Teh API-jev ne izpostavljajte internetu.
Glej [Stefanov predlog](docs/stefan.md).
