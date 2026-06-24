from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ManagedKeyStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    REVOKED = "revoked"


class ManagedKey(Base):
    __tablename__ = "managed_keys"

    key_hash_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    key_alias: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[ManagedKeyStatus] = mapped_column(
        Enum(
            ManagedKeyStatus,
            name="managed_key_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=ManagedKeyStatus.ACTIVE,
        server_default=ManagedKeyStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    blocked_reason: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime)

    spending_limits: Mapped[list["SpendingLimit"]] = relationship(
        back_populates="managed_key",
        cascade="all, delete-orphan",
    )
