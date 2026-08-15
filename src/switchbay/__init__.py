"""switchbay — local single-user workbench over knowledge bases."""

__version__ = "0.9.7"

# Use the OS certificate store for HTTPS (corporate TLS proxies, custom
# CAs). Must run before any aiohttp ClientSession creates an SSL context
# from the default certifi bundle. Fail-soft if truststore is absent so
# unit imports still work without the optional dep fully installed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass
