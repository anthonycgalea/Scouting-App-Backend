from match_predictions import MatchPredictions
from sqlmodel import Field


class MatchPredictions2025(MatchPredictions, table=True):
    __tablename__ = "matchpredictions2025"
    red_auto_rp: float = Field(default=0.0)
    blue_auto_rp: float = Field(default=0.0)
    red_endgame_rp: float = Field(default=0.0)
    blue_endgame_rp: float = Field(default=0.0)

    #coral rp prediction storage
    red_w_coral_rp: float = Field(default=0.0) #if red plays for win, chances they get RP naturally
    blue_w_coral_rp: float = Field(default=0.0) #if blue plays for win, chances they get RP naturally
    red_r_coral_rp: float = Field(default=0.0) #if red plays for rp, chances they get RP
    blue_r_coral_rp: float = Field(default=0.0) #if blue plays for rp, chances they get RP
    red_rw_win_pct: float = Field(default=0.0) #if red plays for rp and blue plays for win, red win percentage
    blue_rw_win_pct: float = Field(default=0.0) #if red plays for rp and blue plays for win, blue win percentage
    red_wr_win_pct: float = Field(default=0.0) #if blue plays for rp and red plays for win, red win percentage
    blue_wr_win_pct: float = Field(default=0.0) #if blue plays for rp and red plays for win, blue win percentage
    red_rr_win_pct: float = Field(default=0.0) #if red and blue play for rp, red win percentage
    blue_rr_win_pct: float = Field(default=0.0) #if red and blue play for rp, blue win percentage