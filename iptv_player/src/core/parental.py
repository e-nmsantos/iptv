"""PIN hashing helpers for the parental-lock feature."""

import hashlib
import hmac
import os
import time
from collections.abc import Callable


def generate_salt() -> str:
    return os.urandom(16).hex()


def hash_pin(pin: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000).hex()


def verify_pin(pin: str, salt_hex: str, hash_hex: str) -> bool:
    if not salt_hex or not hash_hex:
        return False
    return hmac.compare_digest(hash_pin(pin, salt_hex), hash_hex)


class PinAttemptLimiter:
    """In-memory brute-force protection without persisting entered PINs."""

    def __init__(
        self,
        max_attempts: int = 5,
        lock_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._max_attempts = max(1, int(max_attempts))
        self._lock_seconds = max(1, int(lock_seconds))
        self._clock = clock
        self._failures = 0
        self._locked_until = 0.0

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self._locked_until - self._clock() + 0.999))

    def is_allowed(self) -> bool:
        if self._clock() >= self._locked_until:
            if self._locked_until:
                self.reset()
            return True
        return False

    def register_failure(self) -> None:
        if not self.is_allowed():
            return
        self._failures += 1
        if self._failures >= self._max_attempts:
            self._locked_until = self._clock() + self._lock_seconds

    def reset(self) -> None:
        self._failures = 0
        self._locked_until = 0.0
