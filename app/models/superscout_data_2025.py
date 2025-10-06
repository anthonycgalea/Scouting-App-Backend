from sqlmodel import Field

from .superscout_data import SuperScoutData


class SuperScoutData2025(SuperScoutData, table=True):
    __tablename__ = "superscout_2025"
    floor_algae: bool = Field(default=False)
    floor_coral: bool = Field(default=False)
    holds_both_pieces: bool = Field(default=False)

