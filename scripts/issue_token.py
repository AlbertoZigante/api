"""Issue a short-lived bearer token for local testing / a self-run beta (HS256, the same JWT_SECRET the API checks).

    python scripts/issue_token.py --sub alberto            # 1 hour
    python scripts/issue_token.py --sub tester --minutes 15 --aud diy-api --iss https://me.example

Reads JWT_SECRET (and JWT_AUDIENCE / JWT_ISSUER defaults) from the environment / .env. Real users get their tokens from
the identity provider (Supabase / Auth0); this is for you and for scripted checks:

    curl -H "Authorization: Bearer $(python scripts/issue_token.py --sub me)" http://localhost:8000/v1/bom ...
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import MIN_HS_SECRET_CHARS  # noqa: E402
from app.config import get_settings  # noqa: E402


def issue(secret: str, sub: str, minutes: float, aud: str = "", iss: str = "") -> str:
    if len(secret) < MIN_HS_SECRET_CHARS:
        raise SystemExit(f"JWT_SECRET must be at least {MIN_HS_SECRET_CHARS} characters")
    if not sub or len(sub) > 128:
        raise SystemExit("--sub must be 1-128 characters")
    now = int(time.time())
    claims: dict[str, object] = {"sub": sub, "iat": now, "exp": now + int(minutes * 60)}
    if aud:
        claims["aud"] = aud
    if iss:
        claims["iss"] = iss
    return jwt.encode(claims, secret, algorithm="HS256")


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sub", required=True, help="user id (the rate-limit bucket and the log identity)")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--aud", default=settings.jwt_audience)
    ap.add_argument("--iss", default=settings.jwt_issuer)
    args = ap.parse_args()
    print(issue(settings.jwt_secret, args.sub, args.minutes, args.aud, args.iss))


if __name__ == "__main__":
    main()
