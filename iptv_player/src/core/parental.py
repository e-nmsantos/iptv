"""PIN hashing helpers for the parental-lock feature."""

import hashlib
import hmac
import os
import time
from collections.abc import Callable

PBKDF2_ITERATIONS = 600_000
_LEGACY_ITERATIONS = 100_000
_SEPARATOR = "$"


def generate_salt() -> str:
    return os.urandom(16).hex()


def _derive(pin: str, salt_hex: str, iterations: int) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations).hex()


def hash_pin(pin: str, salt_hex: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash a PIN, recording the cost factor as ``<iterations>$<digest>``."""
    return f"{iterations}{_SEPARATOR}{_derive(pin, salt_hex, iterations)}"


def _split_stored(hash_hex: str) -> tuple:
    """Return ``(iterations, digest)`` for current and legacy (bare digest) values."""
    iterations, separator, digest = hash_hex.partition(_SEPARATOR)
    if separator and iterations.isdigit() and digest:
        return int(iterations), digest
    return _LEGACY_ITERATIONS, hash_hex


def needs_rehash(hash_hex: str) -> bool:
    """True when a stored hash predates the current cost factor."""
    iterations, digest = _split_stored(hash_hex)
    return iterations < PBKDF2_ITERATIONS or not digest


def verify_pin(pin: str, salt_hex: str, hash_hex: str) -> bool:
    """Verify a PIN against a stored hash, accepting pre-0.6 iterations."""
    if not salt_hex or not hash_hex:
        return False
    iterations, expected = _split_stored(hash_hex)
    try:
        candidate = _derive(pin, salt_hex, iterations)
    except ValueError:
        return False
    return hmac.compare_digest(candidate, expected)


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
