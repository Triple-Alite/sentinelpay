from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class ExactNumeric(TypeDecorator[Decimal]):
    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int) -> None:
        self.precision = precision
        self.scale = scale
        super().__init__(precision=precision, scale=scale)

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(self.precision + 2))
        return dialect.type_descriptor(Numeric(self.precision, self.scale))

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | Decimal | None:
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        if dialect.name == "sqlite":
            return format(decimal_value, "f")
        return decimal_value

    def process_result_value(self, value: str | Decimal | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))