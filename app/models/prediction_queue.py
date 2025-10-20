from datetime import datetime
from typing import Optional, Type
from uuid import UUID

from sqlalchemy import event, select
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class PredictionQueue(SQLModel, table=True):
    __tablename__="prediction_queue"
    event_key: str = Field(
        foreign_key="frcevent.event_key",
        primary_key=True,
        max_length=15,
    )
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    organization_id: int = Field(primary_key=True, foreign_key="organization.id")