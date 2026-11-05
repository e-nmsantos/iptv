from .settings import Settings

# Application version (X.Y.Z). Kept in sync with the `version` field in
# pyproject.toml, which drives the release manifest and package names.
APP_VERSION = "0.5.2"

# Ed25519 public key (base64, 32 bytes) used to verify signed release
# manifests. Empty means manifests are trusted on HTTPS + SHA-256 alone;
# set it (see scripts/sign_manifest.py) to require a signed manifest.
RELEASE_PUBLIC_KEY = ""

__all__ = ["Settings", "APP_VERSION", "RELEASE_PUBLIC_KEY"]
