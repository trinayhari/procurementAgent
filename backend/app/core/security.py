"""Password hashing + JWT minting/verification and the auth dependency.

Kept dependency-light: `bcrypt` for password hashing and `PyJWT` for the
stateless access tokens. The `get_current_user` dependency decodes the bearer
token and loads the matching user row, raising 401 on any failure."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user import User

# bcrypt caps the input at 72 bytes; longer passwords are truncated to match.
_BCRYPT_MAX_BYTES = 72

# tokenUrl is informational (drives Swagger's "Authorize" form); the real login
# route is /api/auth/login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def hash_password(password: str) -> str:
    digest = bcrypt.hashpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], bcrypt.gensalt())
    return digest.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:_BCRYPT_MAX_BYTES], password_hash.encode("utf-8")
        )
    except ValueError:
        # Malformed/legacy hash — treat as a non-match rather than 500.
        return False


def create_access_token(subject: str) -> str:
    """Mint a signed JWT whose `sub` claim is the user id."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_subject(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency — resolves the bearer token to a User or raises 401."""
    if not token:
        raise _CREDENTIALS_ERROR
    user_id = _decode_subject(token)
    if not user_id:
        raise _CREDENTIALS_ERROR
    user = db.get(User, user_id)
    if user is None:
        raise _CREDENTIALS_ERROR
    return user
