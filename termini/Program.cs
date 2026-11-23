using Npgsql;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddOpenApi();
builder.Services.AddHttpClient();

var connectionString =
    $"Host={Environment.GetEnvironmentVariable("DB_HOST") ?? "localhost"};" +
    $"Port={Environment.GetEnvironmentVariable("DB_PORT") ?? "5432"};" +
    $"Username={Environment.GetEnvironmentVariable("DB_USER") ?? "postgres"};" +
    $"Password={Environment.GetEnvironmentVariable("DB_PASSWORD") ?? "postgres"};" +
    $"Database={Environment.GetEnvironmentVariable("DB_NAME") ?? "termini_db"};";

// NpgsqlDataSource upravlja connection pool-om interno - dobra praksa, ne odpiramo nove konekcije rocno
var podatkovniVir = NpgsqlDataSource.Create(connectionString);
builder.Services.AddSingleton(podatkovniVir);

// Dodeli stabilen ID trenerju tudi ob nadgradnji obstoječe baze.
await using (var migracija = podatkovniVir.CreateCommand("""
    CREATE TABLE IF NOT EXISTS trenerji (id SERIAL PRIMARY KEY, ime VARCHAR(100) NOT NULL UNIQUE);
    ALTER TABLE termini ADD COLUMN IF NOT EXISTS trener_id INTEGER REFERENCES trenerji(id);
    INSERT INTO trenerji (ime) SELECT DISTINCT trener FROM termini ON CONFLICT (ime) DO NOTHING;
    UPDATE termini SET trener_id = trenerji.id FROM trenerji
      WHERE termini.trener = trenerji.ime AND termini.trener_id IS NULL;
    ALTER TABLE termini ALTER COLUMN trener_id SET NOT NULL;
    """))
{
    await migracija.ExecuteNonQueryAsync();
}

var app = builder.Build();
app.MapOpenApi("/openapi.json");

app.MapGet("/health", async (NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("SELECT 1");
    await ukaz.ExecuteScalarAsync();
    return Results.Ok(new { status = "ok" });
}).Produces<Zdravje>(200);

// --- GET: vsi termini ---
app.MapGet("/termini", async (NpgsqlDataSource db) =>
{
    var seznam = new List<object>();
    await using var ukaz = db.CreateCommand("SELECT id, naziv, tip, trener, datum_cas, kapaciteta, aktiven, trener_id FROM termini ORDER BY id");
    await using var bralec = await ukaz.ExecuteReaderAsync();
    while (await bralec.ReadAsync())
    {
        seznam.Add(new
        {
            id = bralec.GetInt32(0),
            naziv = bralec.GetString(1),
            tip = bralec.GetString(2),
            trener = bralec.GetString(3),
            datum_cas = bralec.GetDateTime(4),
            kapaciteta = bralec.GetInt32(5),
            aktiven = bralec.GetBoolean(6),
            trener_id = bralec.GetInt32(7)
        });
    }
    return Results.Ok(seznam);
}).Produces<TerminPodatki[]>(200);

// --- GET: en termin po ID ---
app.MapGet("/termini/{id:int}", async (int id, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("SELECT id, naziv, tip, trener, datum_cas, kapaciteta, aktiven, trener_id FROM termini WHERE id = $1");
    ukaz.Parameters.AddWithValue(id);
    await using var bralec = await ukaz.ExecuteReaderAsync();
    if (!await bralec.ReadAsync())
        return Results.NotFound(new { sporocilo = "Termin ne obstaja." });

    return Results.Ok(new
    {
        id = bralec.GetInt32(0),
        naziv = bralec.GetString(1),
        tip = bralec.GetString(2),
        trener = bralec.GetString(3),
        datum_cas = bralec.GetDateTime(4),
        kapaciteta = bralec.GetInt32(5),
        aktiven = bralec.GetBoolean(6),
        trener_id = bralec.GetInt32(7)
    });
}).Produces<TerminPodatki>(200).Produces<Sporocilo>(404);

// --- GET: ocene za termin (storitev Ocene, prek gateway-a) ---
app.MapGet("/termini/{id:int}/ocena", async (int id, IHttpClientFactory httpClientFactory) =>
{
    var gatewayUrl = Environment.GetEnvironmentVariable("GATEWAY_URL") ?? "http://localhost:8080";
    var client = httpClientFactory.CreateClient();
    using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(3));
    try
    {
        var odgovor = await client.GetAsync($"{gatewayUrl}/ocene/termin/{id}", cts.Token);
        if (!odgovor.IsSuccessStatusCode)
            return Results.Json(new { sporocilo = "Storitev ocen ni dosegljiva." }, statusCode: 503);

        var vsebina = await odgovor.Content.ReadAsStringAsync();
        return Results.Content(vsebina, "application/json");
    }
    catch
    {
        return Results.Json(new { sporocilo = "Storitev ocen ni dosegljiva." }, statusCode: 503);
    }
}).Produces<OcenaPodatki[]>(200).Produces<Sporocilo>(503);

// --- POST: nov termin ---
app.MapPost("/termini", async (TerminVnos vnos, NpgsqlDataSource db) =>
{
    if (string.IsNullOrWhiteSpace(vnos.Trener) || vnos.Trener.Length > 100 ||
        string.IsNullOrWhiteSpace(vnos.Naziv) || vnos.Naziv.Length > 150 ||
        string.IsNullOrWhiteSpace(vnos.Tip) || vnos.Tip.Length > 50 || vnos.Kapaciteta <= 0)
        return Results.BadRequest(new { sporocilo = "Neveljavni podatki." });
    await using var ukaz = db.CreateCommand("""
        WITH trener_vnos AS (
          INSERT INTO trenerji (ime) VALUES ($3) ON CONFLICT (ime) DO UPDATE SET ime=EXCLUDED.ime RETURNING id
        )
        INSERT INTO termini (naziv, tip, trener, datum_cas, kapaciteta, trener_id)
        SELECT $1, $2, $3, $4, $5, id FROM trener_vnos RETURNING id, trener_id
        """);
    ukaz.Parameters.AddWithValue(vnos.Naziv);
    ukaz.Parameters.AddWithValue(vnos.Tip);
    ukaz.Parameters.AddWithValue(vnos.Trener.Trim());
    ukaz.Parameters.AddWithValue(DateTime.SpecifyKind(vnos.DatumCas, DateTimeKind.Unspecified));
    ukaz.Parameters.AddWithValue(vnos.Kapaciteta);
    await using var rezultat = await ukaz.ExecuteReaderAsync();
    await rezultat.ReadAsync();
    var noviId = rezultat.GetInt32(0);
    return Results.Created($"/termini/{noviId}", new { id = noviId, vnos.Naziv, vnos.Tip, trener = vnos.Trener.Trim(), datum_cas = vnos.DatumCas, vnos.Kapaciteta, trener_id = rezultat.GetInt32(1) });
}).Produces<TerminUstvarjen>(201).Produces<Sporocilo>(400);

// --- POST: podvoji termin (npr. za naslednji teden) ---
app.MapPost("/termini/{id:int}/podvoji", async (int id, NpgsqlDataSource db) =>
{
    await using var preveri = db.CreateCommand("SELECT naziv, tip, trener, datum_cas, kapaciteta, trener_id FROM termini WHERE id = $1");
    preveri.Parameters.AddWithValue(id);
    await using var bralec = await preveri.ExecuteReaderAsync();
    if (!await bralec.ReadAsync())
        return Results.NotFound(new { sporocilo = "Termin ne obstaja." });

    var naziv = bralec.GetString(0);
    var tip = bralec.GetString(1);
    var trener = bralec.GetString(2);
    var datumCas = bralec.GetDateTime(3).AddDays(7);
    var kapaciteta = bralec.GetInt32(4);
    var trenerId = bralec.GetInt32(5);
    await bralec.CloseAsync();

    await using var vstavi = db.CreateCommand(
        "INSERT INTO termini (naziv, tip, trener, datum_cas, kapaciteta, trener_id) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id");
    vstavi.Parameters.AddWithValue(naziv);
    vstavi.Parameters.AddWithValue(tip);
    vstavi.Parameters.AddWithValue(trener);
    vstavi.Parameters.AddWithValue(datumCas);
    vstavi.Parameters.AddWithValue(kapaciteta);
    vstavi.Parameters.AddWithValue(trenerId);
    var noviId = (int)(await vstavi.ExecuteScalarAsync())!;

    return Results.Created($"/termini/{noviId}", new { id = noviId, naziv, tip, trener, datum_cas = datumCas, kapaciteta, trener_id = trenerId });
}).Produces<TerminUstvarjen>(201).Produces<Sporocilo>(404);

// --- PUT: izmena termina ---
app.MapPut("/termini/{id:int}", async (int id, TerminVnos vnos, NpgsqlDataSource db) =>
{
    if (string.IsNullOrWhiteSpace(vnos.Trener) || vnos.Trener.Length > 100 ||
        string.IsNullOrWhiteSpace(vnos.Naziv) || vnos.Naziv.Length > 150 ||
        string.IsNullOrWhiteSpace(vnos.Tip) || vnos.Tip.Length > 50 || vnos.Kapaciteta <= 0)
        return Results.BadRequest(new { sporocilo = "Neveljavni podatki." });
    await using var ukaz = db.CreateCommand("""
        WITH trener_vnos AS (
          INSERT INTO trenerji (ime) VALUES ($3) ON CONFLICT (ime) DO UPDATE SET ime=EXCLUDED.ime RETURNING id
        )
        UPDATE termini SET naziv=$1, tip=$2, trener=$3, datum_cas=$4, kapaciteta=$5,
          trener_id=trener_vnos.id FROM trener_vnos WHERE termini.id=$6
        """);
    ukaz.Parameters.AddWithValue(vnos.Naziv);
    ukaz.Parameters.AddWithValue(vnos.Tip);
    ukaz.Parameters.AddWithValue(vnos.Trener.Trim());
    ukaz.Parameters.AddWithValue(DateTime.SpecifyKind(vnos.DatumCas, DateTimeKind.Unspecified));
    ukaz.Parameters.AddWithValue(vnos.Kapaciteta);
    ukaz.Parameters.AddWithValue(id);
    var vrstic = await ukaz.ExecuteNonQueryAsync();
    return vrstic == 0 ? Results.NotFound(new { sporocilo = "Termin ne obstaja." }) : Results.Ok(new { sporocilo = "Termin posodobljen." });
}).Produces<Sporocilo>(200).Produces<Sporocilo>(400).Produces<Sporocilo>(404);

// --- PUT: sprememba statusa (aktiven/odpovedan) ---
app.MapPut("/termini/{id:int}/status", async (int id, StatusVnos vnos, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("UPDATE termini SET aktiven = $1 WHERE id = $2");
    ukaz.Parameters.AddWithValue(vnos.Aktiven);
    ukaz.Parameters.AddWithValue(id);
    var vrstic = await ukaz.ExecuteNonQueryAsync();
    return vrstic == 0 ? Results.NotFound(new { sporocilo = "Termin ne obstaja." }) : Results.Ok(new { sporocilo = "Status posodobljen." });
}).Produces<Sporocilo>(200).Produces<Sporocilo>(404);

// --- DELETE: brisanje enega termina ---
app.MapDelete("/termini/{id:int}", async (int id, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("DELETE FROM termini WHERE id = $1");
    ukaz.Parameters.AddWithValue(id);
    var vrstic = await ukaz.ExecuteNonQueryAsync();
    return vrstic == 0 ? Results.NotFound(new { sporocilo = "Termin ne obstaja." }) : Results.Ok(new { sporocilo = "Termin izbrisan." });
}).Produces<Sporocilo>(200).Produces<Sporocilo>(404);

// --- DELETE: brisanje vseh terminov (admin/test endpoint) ---
app.MapDelete("/termini", async (NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("DELETE FROM termini");
    await ukaz.ExecuteNonQueryAsync();
    return Results.Ok(new { sporocilo = "Vsi termini izbrisani." });
}).Produces<Sporocilo>(200);

app.Run();

record TerminVnos(string Naziv, string Tip, string Trener, DateTime DatumCas, int Kapaciteta);
record StatusVnos(bool Aktiven);
record Zdravje(string status);
record Sporocilo(string sporocilo);
record TerminUstvarjen(int id, string naziv, string tip, string trener, DateTime datum_cas, int kapaciteta, int trener_id);
record TerminPodatki(int id, string naziv, string tip, string trener, DateTime datum_cas, int kapaciteta, bool aktiven, int trener_id);
record OcenaPodatki(int id, int uporabnik_id, int termin_id, int? trener_id, int ocena, string komentar);
