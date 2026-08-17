"""Compatibility namespace for pre-Smallink imports.

New code must import :mod:`smallink`. This package exposes the Smallink package path so older
``link.*`` imports keep working while implementation remains single-sourced.
"""

from importlib import import_module

_smallink = import_module("smallink")

__path__ = _smallink.__path__
__version__ = _smallink.__version__


def __getattr__(name: str):
    return getattr(_smallink, name)
