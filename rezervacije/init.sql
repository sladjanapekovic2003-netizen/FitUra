CREATE TABLE IF NOT EXISTS rezervacije (
    id SERIAL PRIMARY KEY,
    uporabnik_id INTEGER NOT NULL,
    termin_id INTEGER NOT NULL,
    datum_rezervacije TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'aktivna',
    obvestilo_poslano BOOLEAN NOT NULL DEFAULT FALSE
);