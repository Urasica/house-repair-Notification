import asyncio
import hashlib
import hmac
import re
import secrets

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token(auth_token: str) -> str:
    return hmac.digest(auth_token.encode("ascii"), b"repair-guide-csrf-v1", "sha256").hex()


def valid_token(value: str | None) -> bool:
    return value is not None and TOKEN_PATTERN.fullmatch(value) is not None


class Passwords:
    def __init__(self):
        self.hasher = PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID
        )
        self._dummy_hash = self.hasher.hash(new_token())
        self._slots = asyncio.Semaphore(2)

    async def hash(self, password: str) -> str:
        async with self._slots:
            return await to_thread.run_sync(self.hasher.hash, password)

    async def verify(self, encoded: str | None, password: str) -> bool:
        async with self._slots:
            try:
                verified = await to_thread.run_sync(
                    self.hasher.verify, encoded or self._dummy_hash, password
                )
                return verified and encoded is not None
            except (VerificationError, InvalidHashError):
                return False
