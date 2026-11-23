"""Test double mirroring the real Uporabniki and Termini paths and ports."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = self.path.strip("/").split("/")
        resource = "uporabniki" if self.server.server_port == 3001 else "termini"
        valid = len(parts) == 2 and parts[0] == resource and parts[1].isdigit()
        item = int(parts[1]) if valid else 0
        status = 200 if item > 0 and item != 999 else 404
        if status != 200:
            body = {"sporocilo": "Ni zapisa"}
        elif resource == "uporabniki":
            body = {"id": item, "ime": "Test", "email": f"test{item}@example.test"}
        else:
            body = {"id": item, "trener": "Test trener", "aktiven": True}
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


if __name__ == "__main__":
    users = ThreadingHTTPServer(("0.0.0.0", 3001), Handler)
    terms = ThreadingHTTPServer(("0.0.0.0", 3002), Handler)
    Thread(target=users.serve_forever, daemon=True).start()
    terms.serve_forever()
