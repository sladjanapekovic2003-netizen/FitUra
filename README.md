# FitUra – prva naloga

Mikrostoritvena spletna aplikacija za rezervacijo terminov v fitnes centru.
Ekipa: Sladjana in Stefan (Ssqured).

## Razdelitev dela

| Lastnik | Mikrostoritev | Framework | Lokalni port | Status |
|---|---|---|---:|---|
| Sladjana | Članarine | Python / FastAPI | 8001 | Implementirano |
| Sladjana | Obvestila | Python / Flask | 8002 | Implementirano |
| Sladjana | Ocene | Node.js / Express | 8003 | Implementirano |
| Stefan | Uporabniki | Express | 3001 | Veja stefan-dev |
| Stefan | Termini | ASP.NET Core | 3002 | Veja stefan-dev |
| Stefan | Rezervacije | FastAPI | 3003 | Veja stefan-dev |

Vsaka implementirana storitev ima svoj PostgreSQL strežnik, svojo bazo in trajni Docker volume.
Podatkovne baze si ne delijo; komunikacija med storitvami poteka prek skupnega REST API Gateway-a (Nginx).
Uporabljeni so trije različni spletni frameworki.

## Zagon

Potrebujete Git, Docker Desktop, Python 3 (za integracijske teste) in po želji VS Code.
V terminalu v korenu projekta:

```sh
docker compose up --build -d
docker compose ps
```

API Gateway je na http://localhost:8080. Kontejnerji Uporabniki, Termini in
Rezervacije morajo biti ob združitvi na istem Docker omrežju z imeni
`uporabniki`, `termini`, `rezervacije` in notranjimi porti 3001, 3002 in 3003,
skladno s Stefanovo implementacijo.

Dokler Stefanove storitve niso na voljo, lahko lokalno preverimo HTTP pogodbo
s testnim dvojnikom, ki **ni implementacija** njegovih mikrostoritev:

```sh
docker compose -f compose.yaml -f compose.test.yaml up --build -d
python3 tests/test_api.py
docker compose -f compose.yaml -f compose.test.yaml rm -sf test-partner
python3 tests/test_partner_unavailable.py
```

Zadnji test je namenjen stanju brez pravih partnerskih storitev.
Testni dvojnik je samo v dodatni konfiguraciji in ni vključen pri običajnem
zagonu. Končno povezovanje in testiranje z dejanskima storitvama Uporabniki in
Termini je potrebno po njuni implementaciji. Ne zaganjajte dvojnika hkrati z
njunima pravima kontejnerjema.

Prvi zagon lahko traja več minut zaradi prenosa slik. Docker Desktop mora biti vklopljen.
Za ustavitev brez brisanja podatkov uporabite `docker compose down`.
PostgreSQL podatkovne baze niso izpostavljene gostiteljskemu omrežju.
Privzeto geslo je namenjeno izključno lokalnemu razvoju; prepišite ga prek
`POSTGRES_PASSWORD` (npr. v ignorirani datoteki .env) pred prvim zagonom.
SQLite volumni iz prejšnje verzije niso izbrisani ali preneseni; nova baza
se inicializira prazna.

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
| Članarine | /paketi | /clanarina | 4 | 2 | 2 | 2 |
| Obvestila | /obvestila | /nastavitve | 6 | 2 | 2 | 2 |
| Ocene | /ocene | /odgovori | 6 | 2 | 2 | 2 |

Število GET ne vključuje tehničnih poti /health in /openapi.json.
Statusi: 200 (uspeh), 201 (ustvarjeno), 204 (izbrisano),
400 ali 422 (neveljavni podatki), 404 (ni zapisa), 409 (konflikt), 503 (odvisna storitev ni dosegljiva).

Operacije iz prvotnega načrta: GET/POST/PUT `/clanarina` (GET/PUT po ID),
POST `/obvestila`, GET `/obvestila/uporabnik/{id}`, POST `/ocene`,
GET `/ocene/termin/{id}` in GET `/ocene/trener/{id}`.
Pot `/clanarine` ostaja združljiva s prejšnjo različico.
Ocena lahko vsebuje tudi `trener_id`.

## Medsebojna komunikacija prek API Gateway-a

Klici med članoma skupine (vsi preko `http://gateway:8080`):

- Članarine → Uporabniki: GET /uporabniki/{id} pred ustvarjanjem in posodabljanjem članarine.
- Obvestila → Uporabniki: GET /uporabniki/{id} pred ustvarjanjem in posodabljanjem obvestila ali nastavitev.
- Ocene → Termini: GET /termini/{id} pred ustvarjanjem in posodabljanjem ocene.

Če zunanji zapis ne obstaja, storitev vrne 409 in ga ne shrani.
Če je odvisna storitev nedosegljiva, vrne 503. API pogodba je usklajena z dejanskima potema /uporabniki/{id} in /termini/{id}:
200 za obstoječi zapis, 404 za neobstoječega. Po združitvi je treba preveriti
točne poti, podatkovne tipe in po potrebi avtorizacijo s Stefanom.

Dodatne povezave:

- Članarine → Obvestila: POST /obvestila pri ustvarjanju članarine.
- Ocene → Obvestila: POST /obvestila pri ustvarjanju ocene.
- Obvestila → Članarine: GET /clanarine?uporabnik_id=ID za povzetek na
  GET /uporabniki/{user_id}/povzetek.

Članarina/ocena je shranjena tudi, če je storitev za obvestila nedosegljiva.
Polje `obvestilo_poslano` pove, ali je obvestilo uspešno ustvarjeno.
Povzetek vrne 503, če storitev Članarine ni dosegljiva.
Gre za notranja obvestila v aplikaciji, ne za dejansko pošiljanje e-pošte/SMS.

## Ročni primer (Swagger UI ali terminal)

Za spodnje primere morata biti na voljo Uporabniki in Termini (ali testni dvojnik).

Najprej ustvarite paket in si zapišite njegov dejanski ID:

```sh
curl -X POST http://localhost:8080/paketi \
  -H 'Content-Type: application/json' \
  -d '{"naziv":"Mesecni","cena_centov":2999}'
```

Če odgovor vrne ID 1, ustvarite članarino (sicer vnesite vrnjeni ID):

```sh
curl -X POST http://localhost:8080/clanarina \
  -H 'Content-Type: application/json' \
  -d '{"uporabnik_id":1,"paket_id":1,"zacetek":"2026-11-23","konec":"2026-12-23"}'
curl http://localhost:8080/obvestila/uporabnik/1
curl http://localhost:8080/uporabniki/1/povzetek
```

Nato ustvarite oceno:

```sh
curl -X POST http://localhost:8080/ocene \
  -H 'Content-Type: application/json' \
  -d '{"uporabnik_id":1,"termin_id":1,"trener_id":10,"ocena":5,"komentar":"Odlicno"}'
curl http://localhost:8080/ocene/termin/1
curl http://localhost:8080/ocene/trener/10
```

## Datotečna struktura

```text
FitUra/
├── compose.yaml
├── README.md
├── compose.test.yaml
├── gateway/nginx.conf
├── storitve/
│   ├── clanarine/  (app.py, requirements.txt, Dockerfile, openapi.json)
│   ├── obvestila/  (app.py, requirements.txt, Dockerfile, openapi.json)
│   └── ocene/      (app.js, package.json, package-lock.json, Dockerfile, openapi.json)
└── tests/
    ├── test_api.py
    ├── test_partner_unavailable.py
    ├── partner_stub.py
    └── export_openapi.py
```

## Dobre prakse in meje prve naloge

Ločeni PostgreSQL strežniki in volumni, parametrizirane SQL poizvedbe, indeksi za
filtriranje, zapiranje povezav in omejen connection pool, validacija vhodov,
HTTP časovne omejitve, smiselne statusne kode, majhne osnovne Docker slike
(slim in alpine), verzionirane knjižnice, OpenAPI in integracijski testi.
Baze vsebujejo samo lokalne razvojne podatke.
Prva naloga še ne vključuje prijave, avtorizacije, dejanskega plačevanja, frontenda
ali varne produkcijske namestitve. Teh API-jev ne izpostavljajte internetu.
