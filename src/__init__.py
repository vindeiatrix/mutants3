"""Namespace package shim so tests can import ``src.mutants``."""

import importlib


mutants = importlib.import_module("mutants")

__all__ = ["mutants"]
