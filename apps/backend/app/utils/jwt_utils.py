import os
import time
from jose import jwt

JWT_SECRET = os.environ.get('JWT_SECRET', 'change-me')
JWT_ALGORITHM = os.environ.get('JWT_ALGORITHM', 'HS256')
JWT_EXP_SECONDS = int(os.environ.get('JWT_EXP', '3600'))


def create_access_token(subject: str, extra: dict = None):
    now = int(time.time())
    payload = {
        'sub': subject,
        'iat': now,
        'exp': now + JWT_EXP_SECONDS,
        'iss': os.environ.get('JWT_ISS', 'transcript-hub'),
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def decode_token(token: str):
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
