#!/usr/bin/env python3
"""nginx auth_request target: 204 only if the request carries a valid Cloudflare Access JWT for the notes app.

Blocks anyone who reaches the VPS directly (bypassing Cloudflare) or with a forged/expired token.
Config (env): CF_TEAM_DOMAIN=<team>.cloudflareaccess.com, CF_ACCESS_AUD=<application audience tag>.
"""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import jwt

TEAM, AUD = os.environ["CF_TEAM_DOMAIN"], os.environ["CF_ACCESS_AUD"]
KEYS = jwt.PyJWKClient(f"https://{TEAM}/cdn-cgi/access/certs", cache_keys=True)


def valid(token):
    try:
        key = KEYS.get_signing_key_from_jwt(token).key
        jwt.decode(token, key, algorithms=["RS256"], audience=AUD, issuer=f"https://{TEAM}")
        return True
    except Exception:
        return False


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(204 if valid(self.headers.get("Cf-Access-Jwt-Assertion", "")) else 403)
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8091), H).serve_forever()
