CREATE TABLE IF NOT EXISTS termini (
    id SERIAL PRIMARY KEY,
    naziv VARCHAR(150) NOT NULL,
    tip VARCHAR(50) NOT NULL,
    trener VARCHAR(100) NOT NULL,
    datum_cas TIMESTAMP NOT NULL,
    kapaciteta INT NOT NULL CHECK (kapaciteta > 0),
    aktiven BOOLEAN NOT NULL DEFAULT TRUE
);