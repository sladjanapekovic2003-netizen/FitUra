# FitUra – prva naloga

FitUra je mikrostoritvena spletna aplikacija za rezervacijo terminov v fitnes centru.
Ekipa Ssqured: Sladjana Peković in Stefan Barbulović.

## Razdelitev dela in tehnologije

| Mikrostoritev | Razvijalec | Framework | Lokalni port | Podatkovna baza |
|---|---|---|---:|---|
| Uporabniki | Stefan | Node.js / Express | 3001 | uporabniki_db |
| Termini | Stefan | ASP.NET Core | 3002 | termini_db |
| Rezervacije | Stefan | Python / FastAPI | 3003 | rezervacije_db |
| Članarine | Sladjana | Python / FastAPI | 8001 | clanarine |
| Obvestila | Sladjana | Python / Flask | 8002 | obvestila |
| Ocene | Sladjana | Node.js / Express | 8003 | ocene |

Vsaka storitev ima svoj PostgreSQL strežnik, bazo in trajni Docker volume.
Uporabljeni so štirje spletni frameworki. Vse storitve komunicirajo prek REST
API Gateway-a (Nginx) na portu 8080. Baz si med seboj ne delijo.

## Lokalni zagon

Potrebujete Docker Desktop, Git in Python 3 (za integracijske teste).
V korenu združene različice repozitorija:

```sh
docker compose up --build -d
docker compose ps
python3 tests/test_api.py
```

Prvi zagon lahko traja nekaj minut zaradi prenosa Docker slik. Delovati mora
13 kontejnerjev: šest storitev, šest PostgreSQL strežnikov in API Gateway.
Za integracijo se uporabljajo resnične storitve, brez simulatorjev.
Projekt Docker ima ime `fitura-integration` in nove volumne; podatki iz
prejšnjih lokalnih razvojnih projektov ostanejo v svojih volumnih.
Če prejšnji projekt še uporablja iste porte, ga najprej ustavite.
Za ustavitev brez brisanja podatkov uporabite `docker compose down`.

## API dokumentacija

| Storitev | OpenAPI | Interaktivna dokumentacija |
|---|---|---|
| Uporabniki | http://localhost:3001/openapi.json | http://localhost:3001/dokumentacija |
| Termini | http://localhost:3002/openapi.json | uvoz OpenAPI v Postman |
| Rezervacije | http://localhost:3003/openapi.json | http://localhost:3003/docs |
| Članarine | http://localhost:8001/openapi.json | http://localhost:8001/docs |
| Obvestila | http://localhost:8002/openapi.json | uvoz OpenAPI v Postman |
| Ocene | http://localhost:8003/openapi.json | uvoz OpenAPI v Postman |

Vsaka mikrostoritev samostojno izpostavi tudi pot `/health`.
Po spremembi API-ja obnovite izvožene specifikacije:

```sh
python3 tests/export_openapi.py
```

## REST operacije

| Mikrostoritev | GET | POST | PUT | DELETE |
|---|---:|---:|---:|---:|
| Uporabniki | 3 | 2 | 2 | 2 |
| Termini | 3 | 2 | 2 | 2 |
| Rezervacije | 3 | 2 | 2 | 2 |
| Članarine | 4 | 2 | 2 | 2 |
| Obvestila | 6 | 2 | 2 | 2 |
| Ocene | 6 | 2 | 2 | 2 |

Tehnične poti in združljivostni aliasi niso všteti.
Poti `/uporabnik/{id}` in `/clanarina/{id}` iz prvotnega načrta so ohranjene;
tudi množinski različici ostajata na voljo.

## Komunikacija med storitvami

Vsi medsebojni HTTP klici uporabljajo notranji naslov `http://gateway:8080`.

| Vir | Cilj | Namen in pot |
|---|---|---|
| Članarine | Uporabniki | Preverjanje uporabnika: GET /uporabniki/{id} |
| Obvestila | Uporabniki | Preverjanje prejemnika: GET /uporabniki/{id} |
| Ocene | Termini | Preverjanje termina in identifikatorja trenerja: GET /termini/{id} |
| Uporabniki | Članarine | Članarine uporabnika: GET /clanarine?uporabnik_id={id} |
| Termini | Ocene | Ocene termina: GET /ocene/termin/{id} |
| Rezervacije | Obvestila | Potrditev rezervacije: POST /obvestila |

Dodatno Rezervacije preverijo uporabnika in termin, Ocene preverijo uporabnika,
Članarine in Ocene pošljejo obvestilo, Obvestila pa pridobijo članarine za povzetek.

Termini dodelijo stabilen ID trenerju v lastni tabeli `trenerji` glede na njegovo ime.
Pri ustvarjanju termina se še vedno vnese ime trenerja. `GET /termini/{id}`
vrne `trener_id`; Ocene ga samodejno prevzamejo. Če odjemalec poda drug ID,
se zahteva zavrne s 409. Prikaz ocen je mogoč po terminu ali trenerju.

## Primer demonstracije

Vse zahteve lahko pošljete prek Gateway-a na http://localhost:8080, ali neposredno
prek dokumentacije mikrostoritve. V naslednjih korakih uporabite dejanske ID-je iz odgovorov.

1. POST /registracija – `{"ime":"Ana","email":"ana@example.test","geslo":"Lokalno123!"}`.
2. POST /prijava – `{"email":"ana@example.test","geslo":"Lokalno123!"}`.
3. POST /termini – `{"naziv":"Pilates","tip":"Vadba","trener":"Maja","datumCas":"2027-01-15T10:00:00","kapaciteta":12}`.
4. POST /paketi – `{"naziv":"Mesecni","cena_centov":2999}`.
5. POST /clanarina – `{"uporabnik_id":1,"paket_id":1,"zacetek":"2027-01-01","konec":"2027-02-01"}`.
6. POST /rezervacije – `{"uporabnik_id":1,"termin_id":1}`.
7. POST /ocene – `{"uporabnik_id":1,"termin_id":1,"ocena":5,"komentar":"Odlicno"}`.
8. GET /obvestila/uporabnik/1 – obvestila o članarini, rezervaciji in oceni.
9. GET /uporabniki/1/clanarstvo, GET /rezervacije/uporabnik/1 in GET /termini/1/ocena – preverjanje povezav.

Status 201 pomeni uspešno ustvarjen zapis; 200 uspešen odgovor; 204 izbris brez
vsebine; 400/422 neveljavne podatke; 404 manjkajoči zapis; 409 konflikt;
503 nedosegljivo odvisno storitev.

## Struktura

```text
FitUra/
├── compose.yaml
├── gateway/nginx.conf
├── uporabniki/       # Express, Dockerfile, init.sql
├── termini/          # ASP.NET Core, Dockerfile, init.sql
├── rezervacije/      # FastAPI, Dockerfile, init.sql
├── storitve/
│   ├── clanarine/    # FastAPI, Dockerfile
│   ├── obvestila/    # Flask, Dockerfile
│   └── ocene/        # Express, Dockerfile
└── tests/
    ├── test_api.py
    └── export_openapi.py
```

## Dobre prakse in omejitve

Ločene baze in volumni, parametrizirane SQL poizvedbe, indeksi, validacija
vhodov, časovne omejitve HTTP klicev, omejena uporaba povezav, majhne Docker
slike in OpenAPI. Geslo baze je lokalna privzeta vrednost, ki se lahko nadomesti
prek spremenljivke `POSTGRES_PASSWORD` v lokalni datoteki .env pred prvim zagonom.
PostgreSQL strežniki niso izpostavljeni zunaj Docker omrežja, HTTP porti pa
so vezani na localhost.

To je razvojna različica prve naloge, ne produkcijska namestitev.
Frontend, celovita avtorizacija, dejanska plačila, SMS/e-pošta in samodejni
opomniki niso vključeni. Skupinske DELETE operacije so namenjene lokalnim
administrativnim testom; ne uporabljajte jih nad podatki, ki jih želite ohraniti.
