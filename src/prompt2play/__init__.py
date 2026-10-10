"""Prompt2Play's public package interface."""

from importlib.metadata import version
from typing import Final

__version__: Final = version("prompt2play")

__all__ = ["__version__"]
