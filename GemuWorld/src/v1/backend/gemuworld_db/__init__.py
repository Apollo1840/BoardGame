"""GemuWorld V1.1 data layer."""

from .database import connect, migrate

__all__ = ["connect", "migrate"]

