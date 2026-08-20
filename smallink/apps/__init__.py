"""Application platform primitives used by built-in and future Smallink apps."""

from .registry import AppManifest, AppRegistry, builtin_app_registry
from .store import SQLiteAppStore

__all__ = ["AppManifest", "AppRegistry", "SQLiteAppStore", "builtin_app_registry"]
