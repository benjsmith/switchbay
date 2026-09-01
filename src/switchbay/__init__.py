"""switchbay — local single-user workbench over knowledge bases."""

# Keep in lockstep with pyproject.toml — Help → versions and the update
# checker both read this, so drift here makes a current install look
# stale and offers an "update" to a release it is already past.
# tests/unit/test_version_sync.py fails the build if the two diverge.
__version__ = "0.12.9"

# Use the OS certificate store for HTTPS (corporate TLS proxies, custom
# CAs). Must run before any aiohttp ClientSession creates an SSL context
# from the default certifi bundle. Fail-soft if truststore is absent so
# unit imports still work without the optional dep fully installed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass
