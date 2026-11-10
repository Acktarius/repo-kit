"""py-indexer: local lexical code retrieval (SQLite FTS5)."""

__version__ = "0.3.3"
SCHEMA_VERSION = 1
APP_NAME = "py-indexer"
# Installer compatibility: bump when a shared install must not be reused.
# 0.3.3 is required so a 0.3.2 install is not reused.
COMPAT_VERSION = "0.3.3"
# Advertised by --app-id. A 0.2.1 probe does not have this, so it is not reused.
CAPABILITY = "staging-publish"
