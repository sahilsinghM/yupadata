import os, time, types
os.environ.setdefault("CF_TEAM_DOMAIN", "t.cloudflareaccess.com"); os.environ.setdefault("CF_ACCESS_AUD", "aud1")
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import access_check as ac


def test_only_valid_access_tokens_pass(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(ac, "KEYS", types.SimpleNamespace(get_signing_key_from_jwt=lambda t: types.SimpleNamespace(key=key.public_key())))
    tok = lambda **kw: jwt.encode({"aud": "aud1", "iss": "https://t.cloudflareaccess.com", "exp": time.time() + 60, **kw}, key, "RS256")
    assert ac.valid(tok())
    assert not ac.valid(tok(aud="other-app"))
    assert not ac.valid(tok(exp=time.time() - 60))
    assert not ac.valid(tok(iss="https://evil.cloudflareaccess.com"))
    assert not ac.valid("") and not ac.valid("garbage")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert not ac.valid(jwt.encode({"aud": "aud1", "iss": "https://t.cloudflareaccess.com", "exp": time.time() + 60}, other, "RS256"))
