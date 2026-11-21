"""Validate a JWT against a JWKS document.

Checks issuer, audience, an algorithm allowlist, expiry, not-before,
and clock skew. Unknown key ids refresh the JWKS once. RFC 7662
introspection stays a separate option and is not used here.

``none`` and ``HS*`` are rejected. The allowlist is RS256 and ES256.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from dataclasses import dataclass, field

_ALLOWED_ALGS = frozenset({"RS256", "ES256"})
_DEFAULT_SKEW = 60


class TokenError(ValueError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _json_part(text: str) -> dict:
    try:
        data = json.loads(_b64decode(text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise TokenError("token part is not JSON") from exc
    if not isinstance(data, dict):
        raise TokenError("token part is not an object")
    return data


@dataclass
class JWKSCache:
    url: str
    ttl_s: int = 300
    keys: dict[str, dict] = field(default_factory=dict)
    fetched_at: float = 0.0

    def get(self, kid: str, *, force: bool = False) -> dict:
        stale = (time.time() - self.fetched_at) > self.ttl_s
        if force or stale or kid not in self.keys:
            self.refresh()
        key = self.keys.get(kid)
        if key is None:
            raise TokenError(f"no key {kid}")
        return key

    def refresh(self) -> None:
        req = urllib.request.Request(self.url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise TokenError(f"jwks fetch failed: {exc}") from exc
        keys = {}
        for row in data.get("keys") or []:
            if isinstance(row, dict) and row.get("kid"):
                keys[str(row["kid"])] = row
        self.keys = keys
        self.fetched_at = time.time()


def sign_rs256(payload: dict, private_key, *, kid: str) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    sig = private_key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + _b64url(sig)


def validate(
    token: str,
    *,
    cache: JWKSCache,
    issuer: str,
    audience: str,
    skew_s: int = _DEFAULT_SKEW,
    now: float | None = None,
) -> dict:
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise TokenError("token is not a JWT")
    header = _json_part(parts[0])
    payload = _json_part(parts[1])
    alg = str(header.get("alg") or "")
    if alg not in _ALLOWED_ALGS:
        raise TokenError(f"algorithm {alg or 'missing'} is not allowed")
    kid = str(header.get("kid") or "")
    if not kid:
        raise TokenError("missing kid")
    try:
        jwk = cache.get(kid)
    except TokenError:
        jwk = cache.get(kid, force=True)
    _verify(alg, f"{parts[0]}.{parts[1]}".encode("ascii"), _b64decode(parts[2]), jwk)
    now = time.time() if now is None else now
    if str(payload.get("iss") or "") != issuer:
        raise TokenError("issuer mismatch")
    aud = payload.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if audience not in [str(item) for item in audiences if item is not None]:
        raise TokenError("audience mismatch")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        raise TokenError("missing exp")
    if now > float(exp) + skew_s:
        raise TokenError("token expired")
    nbf = payload.get("nbf")
    if nbf is not None:
        if not isinstance(nbf, (int, float)):
            raise TokenError("bad nbf")
        if now + skew_s < float(nbf):
            raise TokenError("token not yet valid")
    return payload


def _verify(alg: str, signing_input: bytes, signature: bytes, jwk: dict) -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
    if alg == "RS256":
        key = _rsa_public(jwk)
        key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        return
    if alg == "ES256":
        key = _ec_public(jwk)
        r, s = _ecdsa_der(signature)
        key.verify(utils.encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256()))
        return
    raise TokenError(alg)


def _rsa_public(jwk: dict):
    from cryptography.hazmat.primitives.asymmetric import rsa
    n = int.from_bytes(_b64decode(jwk["n"]), "big")
    e = int.from_bytes(_b64decode(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _ec_public(jwk: dict):
    from cryptography.hazmat.primitives.asymmetric import ec
    x = int.from_bytes(_b64decode(jwk["x"]), "big")
    y = int.from_bytes(_b64decode(jwk["y"]), "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


def _ecdsa_der(signature: bytes) -> tuple[int, int]:
    if len(signature) != 64:
        raise TokenError("ES256 signature length")
    return int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")


def jwk_from_public_pem(pem: bytes, kid: str) -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, rsa.RSAPublicKey):
        raise TokenError("expected an RSA public key")
    numbers = key.public_numbers()
    n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {"kty": "RSA", "alg": "RS256", "kid": kid, "use": "sig", "n": _b64url(n), "e": _b64url(e)}
