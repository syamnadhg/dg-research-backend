"""Per-user Firebase auth for the BE.

Replaces the Admin-SDK service-account model with a refresh-token credential
scoped to one Firebase user — see PairingRecipe.md §2 for the design.

Public surface:
- keystore: OS keystore wrapper with current/previous/pending slots
- credentials: RefreshTokenCredentials (google.auth.credentials.Credentials)
- pairing: code generation + Firebase sign-in-with-custom-token HTTP
"""

from . import credentials, keystore, pairing

__all__ = ["credentials", "keystore", "pairing"]
