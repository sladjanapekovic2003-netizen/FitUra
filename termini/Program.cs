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

var app = builder.Build();
app.MapOpenApi("/openapi.json");

// --- GET: vsi termini ---
app.MapGet("/termini", async (NpgsqlDataSource db) =>
{
    var seznam = new List<object>();
    await using var ukaz = db.CreateCommand("SELECT id, naziv, tip, trener, datum_cas, kapaciteta, aktiven FROM termini ORDER BY id");
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
            aktiven = bralec.GetBoolean(6)
        });
    }
    return Results.Ok(seznam);
});

// --- GET: en termin po ID ---
app.MapGet("/termini/{id:int}", async (int id, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("SELECT id, naziv, tip, trener, datum_cas, kapaciteta, aktiven FROM termini WHERE id = $1");
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
        aktiven = bralec.GetBoolean(6)
    });
});

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
});

// --- POST: nov termin ---
app.MapPost("/termini", async (TerminVnos vnos, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand(
        "INSERT INTO termini (naziv, tip, trener, datum_cas, kapaciteta) VALUES ($1, $2, $3, $4, $5) RETURNING id");
    ukaz.Parameters.AddWithValue(vnos.Naziv);
    ukaz.Parameters.AddWithValue(vnos.Tip);
    ukaz.Parameters.AddWithValue(vnos.Trener);
    ukaz.Parameters.AddWithValue(vnos.DatumCas);
    ukaz.Parameters.AddWithValue(vnos.Kapaciteta);
    var noviId = (int)(await ukaz.ExecuteScalarAsync())!;
    return Results.Created($"/termini/{noviId}", new { id = noviId, vnos.Naziv, vnos.Tip, vnos.Trener, vnos.DatumCas, vnos.Kapaciteta });
});

// --- POST: podvoji termin (npr. za naslednji teden) ---
app.MapPost("/termini/{id:int}/podvoji", async (int id, NpgsqlDataSource db) =>
{
    await using var preveri = db.CreateCommand("SELECT naziv, tip, trener, datum_cas, kapaciteta FROM termini WHERE id = $1");
    preveri.Parameters.AddWithValue(id);
    await using var bralec = await preveri.ExecuteReaderAsync();
    if (!await bralec.ReadAsync())
        return Results.NotFound(new { sporocilo = "Termin ne obstaja." });

    var naziv = bralec.GetString(0);
    var tip = bralec.GetString(1);
    var trener = bralec.GetString(2);
    var datumCas = bralec.GetDateTime(3).AddDays(7);
    var kapaciteta = bralec.GetInt32(4);
    await bralec.CloseAsync();

    await using var vstavi = db.CreateCommand(
        "INSERT INTO termini (naziv, tip, trener, datum_cas, kapaciteta) VALUES ($1, $2, $3, $4, $5) RETURNING id");
    vstavi.Parameters.AddWithValue(naziv);
    vstavi.Parameters.AddWithValue(tip);
    vstavi.Parameters.AddWithValue(trener);
    vstavi.Parameters.AddWithValue(datumCas);
    vstavi.Parameters.AddWithValue(kapaciteta);
    var noviId = (int)(await vstavi.ExecuteScalarAsync())!;

    return Results.Created($"/termini/{noviId}", new { id = noviId, naziv, tip, trener, datum_cas = datumCas, kapaciteta });
});

// --- PUT: izmena termina ---
app.MapPut("/termini/{id:int}", async (int id, TerminVnos vnos, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand(
        "UPDATE termini SET naziv = $1, tip = $2, trener = $3, datum_cas = $4, kapaciteta = $5 WHERE id = $6");
    ukaz.Parameters.AddWithValue(vnos.Naziv);
    ukaz.Parameters.AddWithValue(vnos.Tip);
    ukaz.Parameters.AddWithValue(vnos.Trener);
    ukaz.Parameters.AddWithValue(vnos.DatumCas);
    ukaz.Parameters.AddWithValue(vnos.Kapaciteta);
    ukaz.Parameters.AddWithValue(id);
    var vrstic = await ukaz.ExecuteNonQueryAsync();
    return vrstic == 0 ? Results.NotFound(new { sporocilo = "Termin ne obstaja." }) : Results.Ok(new { sporocilo = "Termin posodobljen." });
});

// --- PUT: sprememba statusa (aktiven/odpovedan) ---
app.MapPut("/termini/{id:int}/status", async (int id, StatusVnos vnos, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("UPDATE termini SET aktiven = $1 WHERE id = $2");
    ukaz.Parameters.AddWithValue(vnos.Aktiven);
    ukaz.Parameters.AddWithValue(id);
    var vrstic = await ukaz.ExecuteNonQueryAsync();
    return vrstic == 0 ? Results.NotFound(new { sporocilo = "Termin ne obstaja." }) : Results.Ok(new { sporocilo = "Status posodobljen." });
});

// --- DELETE: brisanje enega termina ---
app.MapDelete("/termini/{id:int}", async (int id, NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("DELETE FROM termini WHERE id = $1");
    ukaz.Parameters.AddWithValue(id);
    var vrstic = await ukaz.ExecuteNonQueryAsync();
    return vrstic == 0 ? Results.NotFound(new { sporocilo = "Termin ne obstaja." }) : Results.Ok(new { sporocilo = "Termin izbrisan." });
});

// --- DELETE: brisanje vseh terminov (admin/test endpoint) ---
app.MapDelete("/termini", async (NpgsqlDataSource db) =>
{
    await using var ukaz = db.CreateCommand("DELETE FROM termini");
    await ukaz.ExecuteNonQueryAsync();
    return Results.Ok(new { sporocilo = "Vsi termini izbrisani." });
});

app.Run();

record TerminVnos(string Naziv, string Tip, string Trener, DateTime DatumCas, int Kapaciteta);
record StatusVnos(bool Aktiven);
