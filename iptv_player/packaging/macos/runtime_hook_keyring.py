# PyInstaller runtime hook.
#
# `keyring` normally picks its backend via entry-point/module discovery, which
# does not work reliably inside a frozen PyInstaller bundle. Force the macOS
# Keychain backend explicitly so credential storage keeps working in the
# packaged app.
import sys

if sys.platform == "darwin":
    try:
        import keyring
        from keyring.backends import macOS

        keyring.set_keyring(macOS.Keyring())
    except Exception:
        pass
