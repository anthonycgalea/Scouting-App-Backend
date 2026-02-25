from app.models.tba_match_data_2026 import Endgame2026
from app.services.scout import _parse_tba_breakdown


def test_parse_2026_breakdown_maps_tower_status_and_fuel_counts():
    breakdown = {
        "autoTowerRobot1": "None",
        "autoTowerRobot2": "Level2",
        "autoTowerRobot3": "L3",
        "endGameTowerRobot1": "None",
        "endGameTowerRobot2": "Level2",
        "endGameTowerRobot3": "Level3",
        "hubScore": {
            "autoCount": 39,
            "teleopCount": 84,
        },
    }

    parsed = _parse_tba_breakdown(2026, breakdown, [8724, 190, 2342])

    assert parsed["autoFuel"] == 39
    assert parsed["teleopFuel"] == 84
    assert parsed["bot1AutoClimb"] is False
    assert parsed["bot2AutoClimb"] is True
    assert parsed["bot3AutoClimb"] is True
    assert parsed["bot1endgame"] == Endgame2026.NONE
    assert parsed["bot2endgame"] == Endgame2026.L2
    assert parsed["bot3endgame"] == Endgame2026.L3
