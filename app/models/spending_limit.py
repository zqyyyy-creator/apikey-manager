from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    DECIMAL,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class SpendingLimitType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    TOTAL = "total"


class SpendingLimit(Base):
    __tablename__ = "spending_limits"
    __table_args__ = (
        UniqueConstraint(
            "key_hash_id",
            "limit_type",
            name="uq_spending_limits_key_hash_id_limit_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_hash_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("managed_keys.key_hash_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    limit_type: Mapped[SpendingLimitType] = mapped_column(
        Enum(
            SpendingLimitType,
            name="spending_limit_type",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 4), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8),
        default="CNY",
        server_default="CNY",
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    managed_key: Mapped["ManagedKey"] = relationship(back_populates="spending_limits")
