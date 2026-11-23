"""Test double for the planned Uporabniki and Termini contracts (not production)."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = self.path.strip("/").split("/")
        valid = len(parts) == 2 and parts[0] in ("uporabnik", "termini") and parts[1].isdigit()
        item = int(parts[1]) if valid else 0
        status = 200 if item > 0 and item != 999 else 404
        body = {"id": item, "trener_id": 10} if status == 200 else {"error": "Ni zapisa"}
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
