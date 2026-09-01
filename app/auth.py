"JWT authentication for the /query endpoint."


import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

DEMO_USERNAME = os.environ["DEMO_USERNAME"]
DEMO_PASSWORD_HASH = os.environ["DEMO_PASSWORD_HASH"].encode()  # bcrypt wants bytes

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_demo_user(username: str, password: str) -> bool:
    """Check submitted credentials against the single demo user."""
    if username != DEMO_USERNAME:
        return False
    return bcrypt.checkpw(password.encode(), DEMO_PASSWORD_HASH)


def create_access_token(username: str) -> str:
    """Issue a signed JWT for a successfully authenticated user."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency — add `current_user: str = Depends(get_current_user)`
    to any endpoint's signature to require a valid bearer token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise credentials_exception