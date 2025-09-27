from datetime import datetime
from typing import Optional, Type
from uuid import UUID

from sqlalchemy import event, select
from sqlmodel import Field, SQLModel


class MatchData(SQLModel):
    """Base fields shared by all match data tables."""

    season: int = Field(foreign_key="season.id")
    team_number: int = Field(
        foreign_key="teamrecord.team_number",
        primary_key=True
    )
    event_key: str = Field(
        foreign_key="frcevent.event_key",
        primary_key=True,
        max_length=15,
    )
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    user_id: UUID = Field(primary_key=True, foreign_key="users.id")
    organization_id: int = Field(foreign_key="organization.id")
    timestamp: datetime = Field(default_factory=datetime.now)
    notes: Optional[str] = Field(default="")


def register_match_data_creation_hook(match_model: Type[MatchData]) -> None:
    """Register a SQLAlchemy event hook to create ``DataValidation`` rows.

    Whenever a ``MatchData`` subclass inserts a new record we automatically
    create a matching ``DataValidation`` entry with a ``PENDING`` status.  The
    hook is registered for each concrete ``MatchData`` table via the
    corresponding model module.
    """

    @event.listens_for(match_model, "after_insert")
    def _create_data_validation(mapper, connection, target) -> None:  # type: ignore[override]
        from .data_validation import DataValidation, ValidationStatus

        values = {
            "event_key": target.event_key,
            "match_number": target.match_number,
            "match_level": target.match_level,
            "user_id": target.user_id,
            "team_number": target.team_number,
            "organization_id": target.organization_id,
            "timestamp": target.timestamp,
            "validation_status": ValidationStatus.PENDING,
            "notes": "",
        }

        data_validation = DataValidation.__table__
        exists_query = (
            select(1)
            .select_from(data_validation)
            .where(
                (data_validation.c.event_key == target.event_key)
                & (data_validation.c.match_number == target.match_number)
                & (data_validation.c.match_level == target.match_level)
                & (data_validation.c.user_id == target.user_id)
                & (data_validation.c.team_number == target.team_number)
                & (data_validation.c.organization_id == target.organization_id)
            )
        )

        if connection.execute(exists_query).first() is None:
            connection.execute(data_validation.insert().values(**values))
