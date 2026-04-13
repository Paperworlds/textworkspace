"""textworkspace — meta CLI and package manager for the Paperworlds text- stack."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("textworkspace")
except PackageNotFoundError:
    __version__ = "0.1.1"
