import express from 'express';
import pg from 'pg';

const app = express();
app.use(express.json());
const db = new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 5, connectionTimeoutMillis: 3000 });
const gateway = process.env.GATEWAY_URL || 'http://localhost:8080';
await db.query(`
  CREATE TABLE IF NOT EXISTS ocene (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, uporabnik_id INTEGER NOT NULL,
    termin_id INTEGER NOT NULL, trener_id INTEGER, ocena INTEGER NOT NULL CHECK(ocena BETWEEN 1 AND 5),
    komentar TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS odgovori (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ocena_id INTEGER NOT NULL REFERENCES ocene(id),
    besedilo TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS ocene_termin_idx ON ocene(termin_id);
  CREATE INDEX IF NOT EXISTS ocene_trener_idx ON ocene(trener_id);
`);

const schemas = {
  ocene: {
    uporabnik_id: { type: 'integer', minimum: 1 },
    termin_id: { type: 'integer', minimum: 1 },
    trener_id: { type: 'integer', minimum: 1, nullable: true, description: 'ID iz storitve Termini. Če ni podan, se določi samodejno.' },
    ocena: { type: 'integer', minimum: 1, maximum: 5 },
    komentar: { type: 'string', minLength: 0, maxLength: 500 }
  },
  odgovori: {
    ocena_id: { type: 'integer', minimum: 1 },
    besedilo: { type: 'string', minLength: 1, maxLength: 500 }
  }
};

function validate(data, fields) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || Object.keys(data).some(k => !Object.hasOwn(fields, k))) return false;
  return Object.entries(fields).every(([key, rule]) => {
    const value = data[key];
    if (rule.nullable && (value === undefined || value === null)) return true;
    return rule.type === 'integer'
      ? Number.isSafeInteger(value) && value >= rule.minimum && value <= (rule.maximum ?? Number.MAX_SAFE_INTEGER)
      : typeof value === 'string' && value.length >= rule.minLength && value.length <= rule.maxLength;
  });
}

function fail(res, status, error) { return res.status(status).json({ error }); }

async function notify(user) {
  try {
    const res = await fetch(gateway + '/obvestila', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uporabnik_id: user, sporocilo: 'Hvala za vašo oceno.', prebrano: false }),
      signal: AbortSignal.timeout(3000)
    });
    return res.ok;
  } catch { return false; }
}

async function verifyTerm(data, res) {
  try {
    const response = await fetch(gateway + '/termini/' + data.termin_id, { signal: AbortSignal.timeout(3000) });
    if (response.status === 404) { fail(res, 409, 'Termin ne obstaja.'); return false; }
    if (!response.ok) { fail(res, 503, 'Storitev terminov ni dosegljiva.'); return false; }
    const term = await response.json();
    if (!Number.isInteger(term.trener_id) || term.trener_id <= 0) {
      fail(res, 503, 'Termin nima veljavnega ID trenerja.'); return false;
    }
    if (data.trener_id != null && data.trener_id !== term.trener_id) {
      fail(res, 409, 'Trener ne pripada temu terminu.'); return false;
    }
    data.trener_id = term.trener_id;
    return true;
  } catch { fail(res, 503, 'Storitev terminov ni dosegljiva.'); return false; }
}

async function verifyUser(data, res) {
  try {
    const response = await fetch(gateway + '/uporabniki/' + data.uporabnik_id, { signal: AbortSignal.timeout(3000) });
    if (response.status === 404) { fail(res, 409, 'Uporabnik ne obstaja.'); return false; }
    if (!response.ok) { fail(res, 503, 'Storitev uporabnikov ni dosegljiva.'); return false; }
    return true;
  } catch { fail(res, 503, 'Storitev uporabnikov ni dosegljiva.'); return false; }
}

const asyncRoute = fn => (req, res, next) => Promise.resolve(fn(req, res)).catch(next);
const validId = id => /^\d+$/.test(id) && Number.isSafeInteger(Number(id)) && Number(id) > 0 && Number(id) <= 2147483647;

for (const [route, column] of [['termin', 'termin_id'], ['trener', 'trener_id']]) {
  app.get('/ocene/' + route + '/:id', asyncRoute(async (req, res) => {
    if (!validId(req.params.id)) return fail(res, 400, 'Neveljaven ID.');
    res.json((await db.query(`SELECT * FROM ocene WHERE ${column}=$1 ORDER BY id`, [Number(req.params.id)])).rows);
  }));
}

for (const [table, fields] of Object.entries(schemas)) {
  const keys = Object.keys(fields);
  const get = async id => (await db.query(`SELECT * FROM ${table} WHERE id=$1`, [id])).rows[0];
  app.get('/' + table, asyncRoute(async (req, res) => res.json((await db.query(`SELECT * FROM ${table} ORDER BY id`)).rows)));
  app.get('/' + table + '/:id', asyncRoute(async (req, res) => {
    const row = validId(req.params.id) && await get(Number(req.params.id));
    return row ? res.json(row) : fail(res, 404, 'Zapis ne obstaja.');
  }));
  app.post('/' + table, async (req, res, next) => {
    try {
      const data = req.body;
      if (!validate(data, fields)) return fail(res, 400, 'Neveljavni podatki.');
      if (table === 'ocene' && (!await verifyTerm(data, res) || !await verifyUser(data, res))) return;
      const result = await db.query(`INSERT INTO ${table} (${keys.join(',')}) VALUES (${keys.map((_, i) => '$' + (i + 1)).join(',')}) RETURNING *`, keys.map(k => data[k] ?? null));
      const row = result.rows[0];
      if (table === 'ocene') row.obvestilo_poslano = await notify(data.uporabnik_id);
      return res.status(201).json(row);
    } catch (err) { next(err); }
  });
  app.put('/' + table + '/:id', asyncRoute(async (req, res) => {
    const id = Number(req.params.id);
    if (!validId(req.params.id) || !await get(id)) return fail(res, 404, 'Zapis ne obstaja.');
    if (!validate(req.body, fields)) return fail(res, 400, 'Neveljavni podatki.');
    if (table === 'ocene' && (!await verifyTerm(req.body, res) || !await verifyUser(req.body, res))) return;
    const result = await db.query(`UPDATE ${table} SET ${keys.map((k, i) => k + '=$' + (i + 1)).join(',')} WHERE id=$${keys.length + 1} RETURNING *`, [...keys.map(k => req.body[k] ?? null), id]);
    return result.rows[0] ? res.json(result.rows[0]) : fail(res, 404, 'Zapis ne obstaja.');
  }));
  app.delete('/' + table + '/:id', asyncRoute(async (req, res) => {
    const id = Number(req.params.id);
    if (!validId(req.params.id) || !(await db.query(`DELETE FROM ${table} WHERE id=$1`, [id])).rowCount) return fail(res, 404, 'Zapis ne obstaja.');
    return res.status(204).end();
  }));
}

app.get('/health', asyncRoute(async (req, res) => { await db.query('SELECT 1'); res.json({ status: 'ok' }); }));
const json = (schema, description = 'Uspeh') => ({ description, content: { 'application/json': { schema } } });
app.get('/openapi.json', (req, res) => {
  const paths = {};
  const err = { description: 'Napaka' };
  for (const [table, properties] of Object.entries(schemas)) {
    const body = { type: 'object', properties, required: Object.keys(properties).filter(k => !properties[k].nullable), additionalProperties: false };
    const result = { type: 'object', properties: { id: { type: 'integer' }, ...properties }, required: ['id', ...Object.keys(properties)] };
    const created = table === 'ocene' ? { ...result, properties: { ...result.properties, obvestilo_poslano: { type: 'boolean' } }, required: [...result.required, 'obvestilo_poslano'] } : result;
    const requestBody = { required: true, content: { 'application/json': { schema: body } } };
    const fk = table === 'odgovori' ? { 409: err } : { 409: err, 503: err };
    paths['/' + table] = {
      get: { responses: { 200: json({ type: 'array', items: result }) } },
      post: { requestBody, responses: { 201: json(created), 400: err, ...fk } }
    };
    paths['/' + table + '/{id}'] = {
      parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'integer', minimum: 1 } }],
      get: { responses: { 200: json(result), 404: err } },
      put: { requestBody, responses: { 200: json(result), 400: err, 404: err, ...fk } },
      delete: { responses: { 204: { description: 'Izbrisano' }, 404: err, ...(table === 'ocene' ? { 409: err } : {}) } }
    };
    if (table === 'ocene') {
      for (const route of ['termin', 'trener']) paths['/ocene/' + route + '/{id}'] = {
        parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'integer', minimum: 1 } }],
        get: { responses: { 200: json({ type: 'array', items: result }), 400: err } }
      };
    }
  }
  paths['/health'] = { get: { responses: { 200: json({ type: 'object', properties: { status: { type: 'string' } } }) } } };
  res.json({ openapi: '3.0.3', info: { title: 'FitUra - Ocene', version: '1.0.0' }, paths });
});
app.use((err, req, res, next) => {
  if (err instanceof SyntaxError && err.status === 400) return fail(res, 400, 'Neveljaven JSON.');
  if (err.code === '23503') return fail(res, 409, 'Povezan zapis ne obstaja ali je v uporabi.');
  console.error(err);
  return fail(res, 500, 'Napaka strežnika.');
});
app.listen(8000, '0.0.0.0', () => console.log('Ocene listening on 8000'));
