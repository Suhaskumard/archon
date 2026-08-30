"""Custom SQLAlchemy column types."""

from __future__ import annotations

import enum

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class EnumString(TypeDecorator):
    """Store a ``str``-valued Enum as a plain VARCHAR (no DB CHECK constraint).

    Used for enums whose membership grows across project phases (e.g. ``DependencyKind``)
    so adding a value never needs a constraint migration. Validation still happens at the
    application boundary: an unknown string raises ``ValueError`` on write.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[enum.Enum], length: int = 40, **kw) -> None:
        self._enum = enum_cls
        super().__init__(length=length, **kw)

    def process_bind_param(self, value, _dialect):  # noqa: ANN001
        if value is None:
            return None
        if isinstance(value, self._enum):
            return value.value
        return self._enum(value).value  # validates arbitrary strings

    def process_result_value(self, value, _dialect):  # noqa: ANN001
        return None if value is None else self._enum(value)
