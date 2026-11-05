"""Parental-lock PIN hashing, cost factor and legacy hash migration."""

import hashlib

from src.core.parental import (
    PBKDF2_ITERATIONS,
    PinAttemptLimiter,
    generate_salt,
    hash_pin,
    needs_rehash,
    verify_pin,
)


class TestPinHashing:
    def test_uses_the_current_cost_factor(self):
        assert PBKDF2_ITERATIONS >= 600_000

        salt = generate_salt()
        stored = hash_pin("1234", salt)

        iterations, _, digest = stored.partition("$")
        assert iterations == str(PBKDF2_ITERATIONS)
        assert len(digest) == 64

    def test_round_trip_and_rejection(self):
        salt = generate_salt()
        stored = hash_pin("1234", salt)

        assert verify_pin("1234", salt, stored)
        assert not verify_pin("4321", salt, stored)
        assert not verify_pin("1234", generate_salt(), stored)

    def test_empty_credentials_never_verify(self):
        salt = generate_salt()

        assert not verify_pin("1234", "", hash_pin("1234", salt))
        assert not verify_pin("1234", salt, "")

    def test_invalid_salt_is_rejected(self):
        assert not verify_pin("1234", "zz", hash_pin("1234", generate_salt()))

    def test_tampered_digest_is_rejected(self):
        salt = generate_salt()
        stored = hash_pin("1234", salt)

        assert not verify_pin("1234", salt, stored[:-1] + ("0" if stored[-1] != "0" else "1"))


class TestLegacyMigration:
    def test_legacy_100k_hash_still_verifies(self):
        salt = generate_salt()
        legacy = hashlib.pbkdf2_hmac("sha256", b"1234", bytes.fromhex(salt), 100_000).hex()

        assert verify_pin("1234", salt, legacy)
        assert not verify_pin("4321", salt, legacy)
        assert needs_rehash(legacy)

    def test_current_hash_needs_no_migration(self):
        salt = generate_salt()

        assert not needs_rehash(hash_pin("1234", salt))

    def test_malformed_stored_value_is_rejected(self):
        salt = generate_salt()

        assert not verify_pin("1234", salt, "600000$")
        assert not verify_pin("1234", salt, "abc$def")
        assert needs_rehash("600000$")


class TestPinAttemptLimiter:
    def test_locks_after_max_attempts_and_recovers(self):
        now = [0.0]
        limiter = PinAttemptLimiter(max_attempts=2, lock_seconds=30, clock=lambda: now[0])

        limiter.register_failure()
        assert limiter.is_allowed()
        limiter.register_failure()
        assert not limiter.is_allowed()
        assert limiter.remaining_seconds == 30

        now[0] += 30
        assert limiter.is_allowed()
