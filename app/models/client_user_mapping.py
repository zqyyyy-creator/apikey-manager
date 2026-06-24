from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ClientUserMapping(Base):
    __tablename__ = "client_user_mapping"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
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
