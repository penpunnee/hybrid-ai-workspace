"""tool `weather` ของ agent: ไม่ส่ง city = เมืองบ้าน ไม่ใช่ Bangkok (ต่อ 102)

เดิม default "Bangkok" — พอ active_learning ปล่อย "ที่บ้าน…" ผ่าน (ต่อ 102) agent ที่ไม่ส่ง city
จะได้อากาศกรุงเทพแทนแพร่ (บั๊กชนิดเดียวกับต่อ 89 ที่ไม่ระบุเมือง = Bangkok)
"""
from agents import tools as t
from utils import websearch as ws


def test_ไม่ส่ง_city_ใช้เมืองบ้าน(monkeypatch):
    seen = []
    monkeypatch.setattr(ws, "fetch_weather_by_city", lambda c: seen.append(c) or "ok")
    t._t_weather()
    assert seen == [ws.WEATHER_HOME_CITY]


def test_schema_บอกเมืองบ้านให้โมเดลรู้():
    city = t._ALL_TOOLS["weather"]["parameters"]["properties"]["city"]
    assert city["default"] == ws.WEATHER_HOME_CITY
    assert ws.WEATHER_HOME_CITY in city["description"]
    assert "บ้าน" in city["description"]
