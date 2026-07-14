"""Custom static files storage.

WhiteNoise's manifest storage raises a hard ValueError (→ HTTP 500) when a
template references a static file that isn't in the collectstatic manifest.
`manifest_strict = False` makes it fall back to the un-hashed path instead, so a
missing/stale entry degrades to a broken link rather than crashing the request.
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class ResilientManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False
