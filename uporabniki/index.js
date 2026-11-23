const express = require('express');
const cors = require('cors');
const bcrypt = require('bcrypt');
const swaggerUi = require('swagger-ui-express');
const bazenPovezav = require('./baza');
const specifikacija = require('./swagger');
require('dotenv').config();

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3001;

app.use('/dokumentacija', swaggerUi.serve, swaggerUi.setup(specifikacija));
app.get('/openapi.json', (req, res) => res.json(specifikacija));

/**
 * @openapi
 * /uporabniki:
 *   get:
 *     summary: Pridobi seznam vseh uporabnikov
 *     responses:
 *       200:
 *         description: Seznam uporabnikov
 */
app.get('/uporabniki', async (req, res) => {
    try {
        const rezultat = await bazenPovezav.query(
            'SELECT id, ime, email, datum_registracije FROM uporabniki ORDER BY id'
        );
        res.json(rezultat.rows);
    } catch (napaka) {
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri pridobivanju uporabnikov.' });
    }
});

/**
 * @openapi
 * /uporabniki/{id}:
 *   get:
 *     summary: Pridobi enega uporabnika po ID-ju
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: integer
 *     responses:
 *       200:
 *         description: Podatki uporabnika
 *       404:
 *         description: Uporabnik ne obstaja
 */
app.get('/uporabniki/:id', async (req, res) => {
    try {
        const rezultat = await bazenPovezav.query(
            'SELECT id, ime, email, datum_registracije FROM uporabniki WHERE id = $1',
            [req.params.id]
        );
        if (rezultat.rows.length === 0) {
            return res.status(404).json({ sporocilo: 'Uporabnik ne obstaja.' });
        }
        res.json(rezultat.rows[0]);
    } catch (napaka) {
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri pridobivanju uporabnika.' });
    }
});

/**
 * @openapi
 * /registracija:
 *   post:
 *     summary: Registracija novega uporabnika
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               ime:
 *                 type: string
 *               email:
 *                 type: string
 *               geslo:
 *                 type: string
 *     responses:
 *       201:
 *         description: Uporabnik ustvarjen
 *       409:
 *         description: Email že obstaja
 */
app.post('/registracija', async (req, res) => {
    const { ime, email, geslo } = req.body;
    if (!ime || !email || !geslo) {
        return res.status(400).json({ sporocilo: 'Manjkajo obvezni podatki.' });
    }
    try {
        const geslo_hash = await bcrypt.hash(geslo, 10);
        const rezultat = await bazenPovezav.query(
            'INSERT INTO uporabniki (ime, email, geslo_hash) VALUES ($1, $2, $3) RETURNING id, ime, email',
            [ime, email, geslo_hash]
        );
        res.status(201).json(rezultat.rows[0]);
    } catch (napaka) {
        if (napaka.code === '23505') {
            return res.status(409).json({ sporocilo: 'Email je že registriran.' });
        }
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri registraciji.' });
    }
});

/**
 * @openapi
 * /prijava:
 *   post:
 *     summary: Prijava uporabnika
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               email:
 *                 type: string
 *               geslo:
 *                 type: string
 *     responses:
 *       200:
 *         description: Uspešna prijava
 *       401:
 *         description: Napačen email ali geslo
 */
app.post('/prijava', async (req, res) => {
    const { email, geslo } = req.body;
    try {
        const rezultat = await bazenPovezav.query(
            'SELECT * FROM uporabniki WHERE email = $1',
            [email]
        );
        if (rezultat.rows.length === 0) {
            return res.status(401).json({ sporocilo: 'Napačen email ali geslo.' });
        }
        const uporabnik = rezultat.rows[0];
        const ujema = await bcrypt.compare(geslo, uporabnik.geslo_hash);
        if (!ujema) {
            return res.status(401).json({ sporocilo: 'Napačen email ali geslo.' });
        }
        res.json({ id: uporabnik.id, ime: uporabnik.ime, email: uporabnik.email });
    } catch (napaka) {
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri prijavi.' });
    }
});

/**
 * @openapi
 * /uporabniki/{id}:
 *   put:
 *     summary: Urejanje profila uporabnika
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: integer
 *     requestBody:
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               ime:
 *                 type: string
 *               email:
 *                 type: string
 *     responses:
 *       200:
 *         description: Uporabnik posodobljen
 *       404:
 *         description: Uporabnik ne obstaja
 */
app.put('/uporabniki/:id', async (req, res) => {
    const { ime, email } = req.body;
    try {
        const rezultat = await bazenPovezav.query(
            'UPDATE uporabniki SET ime = COALESCE($1, ime), email = COALESCE($2, email) WHERE id = $3 RETURNING id, ime, email',
            [ime, email, req.params.id]
        );
        if (rezultat.rows.length === 0) {
            return res.status(404).json({ sporocilo: 'Uporabnik ne obstaja.' });
        }
        res.json(rezultat.rows[0]);
    } catch (napaka) {
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri urejanju uporabnika.' });
    }
});

/**
 * @openapi
 * /uporabniki/{id}/geslo:
 *   put:
 *     summary: Sprememba gesla
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: integer
 *     requestBody:
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               staro_geslo:
 *                 type: string
 *               novo_geslo:
 *                 type: string
 *     responses:
 *       200:
 *         description: Geslo spremenjeno
 *       401:
 *         description: Staro geslo ni pravilno
 */
app.put('/uporabniki/:id/geslo', async (req, res) => {
    const { staro_geslo, novo_geslo } = req.body;
    try {
        const rezultat = await bazenPovezav.query(
            'SELECT geslo_hash FROM uporabniki WHERE id = $1',
            [req.params.id]
        );
        if (rezultat.rows.length === 0) {
            return res.status(404).json({ sporocilo: 'Uporabnik ne obstaja.' });
        }
        const ujema = await bcrypt.compare(staro_geslo, rezultat.rows[0].geslo_hash);
        if (!ujema) {
            return res.status(401).json({ sporocilo: 'Staro geslo ni pravilno.' });
        }
        const nov_hash = await bcrypt.hash(novo_geslo, 10);
        await bazenPovezav.query(
            'UPDATE uporabniki SET geslo_hash = $1 WHERE id = $2',
            [nov_hash, req.params.id]
        );
        res.json({ sporocilo: 'Geslo uspešno spremenjeno.' });
    } catch (napaka) {
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri spremembi gesla.' });
    }
});

/**
 * @openapi
 * /uporabniki/{id}:
 *   delete:
 *     summary: Izbriši enega uporabnika
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: integer
 *     responses:
 *       200:
 *         description: Uporabnik izbrisan
 *       404:
 *         description: Uporabnik ne obstaja
 */
app.delete('/uporabniki/:id', async (req, res) => {
    try {
        const rezultat = await bazenPovezav.query(
            'DELETE FROM uporabniki WHERE id = $1 RETURNING id',
            [req.params.id]
        );
        if (rezultat.rows.length === 0) {
            return res.status(404).json({ sporocilo: 'Uporabnik ne obstaja.' });
        }
        res.json({ sporocilo: 'Uporabnik izbrisan.' });
    } catch (napaka) {
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri brisanju uporabnika.' });
    }
});

/**
 * @openapi
 * /uporabniki:
 *   delete:
 *     summary: Izbriši vse uporabnike (admin/test endpoint)
 *     responses:
 *       200:
 *         description: Vsi uporabniki izbrisani
 */
app.delete('/uporabniki', async (req, res) => {
    try {
        await bazenPovezav.query('DELETE FROM uporabniki');
        res.json({ sporocilo: 'Vsi uporabniki izbrisani.' });
    } catch (napaka) {
        console.error(napaka);
        res.status(500).json({ sporocilo: 'Napaka pri brisanju uporabnikov.' });
    }
});

app.listen(PORT, () => {
    console.log(`Storitev Uporabniki posluša na portu ${PORT}`);
});