import express from 'express';
import { DatabaseSync } from 'node:sqlite';

const app = express();
app.use(express.json());
const db = new DatabaseSync(process.env.DB_PATH || 'ocene.db');
db.exec(`
  PRAGMA foreign_keys = ON;
  CREATE TABLE IF NOT EXISTS ocene (
    id INTEGER PRIMARY KEY AUTOINCREMENT, uporabnik_id INTEGER NOT NULL,
    termin_id INTEGER NOT NULL, ocena INTEGER NOT NULL CHECK(ocena BETWEEN 1 AND 5),
    komentar TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS odgovori (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ocena_id INTEGER NOT NULL REFERENCES ocene(id),
    besedilo TEXT NOT NULL
  );
`);

const schemas = {
  ocene: {
    uporabnik_id: { type: 'integer', minimum: 1 },
    termin_id: { type: 'integer', minimum: 1 },
    ocena: { type: 'integer', minimum: 1, maximum: 5 },
    komentar: { type: 'string', minLength: 0, maxLength: 500 }
  },
  odgovori: {
    ocena_id: { type: 'integer', minimum: 1 },
    besedilo: { type: 'string', minLength: 1, maxLength: 500 }
  }
};

function validate(data, fields) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || Object.keys(data).length !== Object.keys(fields).length) return false;
  return Object.entries(fields).every(([key, rule]) => {
    const value = data[key];
    return rule.type === 'integer'
      ? Number.isSafeInteger(value) && value >= rule.minimum && value <= (rule.maximum ?? Number.MAX_SAFE_INTEGER)
      : typeof value === 'string' && value.length >= rule.minLength && value.length <= rule.maxLength;
  });
}

function fail(res, status, error) { return res.status(status).json({ error }); }

async function notify(user) {
  try {
    const res = await fetch((process.env.OBVESTILA_URL || 'http://localhost:8002') + '/obvestila', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uporabnik_id: user, sporocilo: 'Hvala za vašo oceno.', prebrano: false }),
      signal: AbortSignal.timeout(3000)
    });
    return res.ok;
  } catch { return false; }
}

for (const [table, fields] of Object.entries(schemas)) {
  const keys = Object.keys(fields);
  const get = id => db.prepare(`SELECT * FROM ${table} WHERE id=?`).get(id);
  const validId = id => /^\d+$/.test(id) && Number.isSafeInteger(Number(id)) && Number(id) > 0;
  const fkValid = data => table !== 'odgovori' || !!db.prepare('SELECT id FROM ocene WHERE id=?').get(data.ocena_id);
  app.get('/' + table, (req, res) => res.json(db.prepare(`SELECT * FROM ${table} ORDER BY id`).all()));
  app.get('/' + table + '/:id', (req, res) => {
    const row = validId(req.params.id) && get(Number(req.params.id));
    return row ? res.json(row) : fail(res, 404, 'Zapis ne obstaja.');
  });
  app.post('/' + table, async (req, res, next) => {
    try {
      const data = req.body;
      if (!validate(data, fields)) return fail(res, 400, 'Neveljavni podatki.');
      if (!fkValid(data)) return fail(res, 409, 'Ocena ne obstaja.');
      const result = db.prepare(`INSERT INTO ${table} (${keys.join(',')}) VALUES (${keys.map(() => '?').join(',')})`).run(...keys.map(k => data[k]));
      const row = get(result.lastInsertRowid);
      if (table === 'ocene') row.obvestilo_poslano = await notify(data.uporabnik_id);
      return res.status(201).json(row);
    } catch (err) { next(err); }
  });
  app.put('/' + table + '/:id', (req, res) => {
    const id = Number(req.params.id);
    if (!validId(req.params.id) || !get(id)) return fail(res, 404, 'Zapis ne obstaja.');
    if (!validate(req.body, fields)) return fail(res, 400, 'Neveljavni podatki.');
    if (!fkValid(req.body)) return fail(res, 409, 'Ocena ne obstaja.');
    db.prepare(`UPDATE ${table} SET ${keys.map(k => k + '=?').join(',')} WHERE id=?`).run(...keys.map(k => req.body[k]), id);
    return res.json(get(id));
  });
  app.delete('/' + table + '/:id', (req, res) => {
    const id = Number(req.params.id);
    if (!validId(req.params.id) || !get(id)) return fail(res, 404, 'Zapis ne obstaja.');
    if (table === 'ocene' && db.prepare('SELECT id FROM odgovori WHERE ocena_id=?').get(id)) return fail(res, 409, 'Ocena ima odgovore.');
    db.prepare(`DELETE FROM ${table} WHERE id=?`).run(id);
    return res.status(204).end();
  });
}

app.get('/health', (req, res) => res.json({ status: 'ok' }));
const json = (schema, description = 'Uspeh') => ({ description, content: { 'application/json': { schema } } });
app.get('/openapi.json', (req, res) => {
  const paths = {};
  const err = { description: 'Napaka' };
  for (const [table, properties] of Object.entries(schemas)) {
    const body = { type: 'object', properties, required: Object.keys(properties), additionalProperties: false };
    const result = { type: 'object', properties: { id: { type: 'integer' }, ...properties }, required: ['id', ...Object.keys(properties)] };
    const created = table === 'ocene' ? { ...result, properties: { ...result.properties, obvestilo_poslano: { type: 'boolean' } }, required: [...result.required, 'obvestilo_poslano'] } : result;
    const requestBody = { required: true, content: { 'application/json': { schema: body } } };
    const fk = table === 'odgovori' ? { 409: err } : {};
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
  }
  paths['/health'] = { get: { responses: { 200: json({ type: 'object', properties: { status: { type: 'string' } } }) } } };
  res.json({ openapi: '3.0.3', info: { title: 'FitUra - Ocene', version: '1.0.0' }, paths });
});
app.use((err, req, res, next) => {
  if (err instanceof SyntaxError && err.status === 400) return fail(res, 400, 'Neveljaven JSON.');
  console.error(err);
  return fail(res, 500, 'Napaka strežnika.');
});
app.listen(8000, '0.0.0.0', () => console.log('Ocene listening on 8000'));
