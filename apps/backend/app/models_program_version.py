from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Text, DateTime, ForeignKey
import uuid
from .models import Base, int_pk


class ProgramVersion(Base):
    __tablename__ = 'program_versions'

    id: Mapped[int] = int_pk()
    program_criteria_id: Mapped[int] = mapped_column(ForeignKey('program_criteria.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    program = relationship('ProgramCriteria', lazy='joined')
