"""
ndev: Fast, cross-platform PHP developer environment for Windows and Linux.
"""
__version__ = "0.3.3"

from . import common as common
from .common.logger import logger as logger
from .common import constants as constants

__all__ = ["__version__", "common", "logger", "constants"]
