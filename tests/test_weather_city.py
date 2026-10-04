"""คำถามอากาศต้องได้เมืองที่ถามจริง — ต่อ 89 (2026-10-04)

prod 13:55: "เช็คว่าวันนี้ ที่บ้าน แพร่ ตอนเย็นจะมีฝนตกไหม" → `_extract_city` รู้จักแค่ 8 เมือง
ไม่เจอ = Bangkok ⇒ ส่งอากาศกรุงเทพให้ (ขวัญบอกตรงๆ ว่าเป็นของกรุงเทพ แต่ตอบคำถามไม่ได้)
- ครบ 77 จังหวัด · ไม่ระบุเมือง / "ที่บ้าน" = เมืองบ้าน (`WEATHER_HOME_CITY`)
- ชื่อที่เป็นคำทั่วไปด้วย (ตาก/เลย/แพร่ …) ต้องมีคำนำหน้าบอกสถานที่ — "ตากผ้า" "ได้เลย" "เผยแพร่" ไม่ใช่จังหวัด
"""
import pytest

from utils import websearch as ws


@pytest.fixture(autouse=True)
def home(monkeypatch):
    monkeypatch.setattr(ws, "WEATHER_HOME_CITY", "HomeTown")


@pytest.mark.parametrize("q,city", [
    ("เช็คว่าวันนี้ ที่บ้าน แพร่ ตอนเย็นจะมีฝนตกไหม", "Phrae"),     # ข้อความจริง prod
    ("เช็คว่าวันนี้ที่แพร่ ฝนจะตกไหมตอนเย็น", "Phrae"),
    ("อากาศจังหวัดน่านพรุ่งนี้", "Nan"),
    ("พยากรณ์อากาศ จ.เลย", "Loei"),
    ("ฝนตกที่ตากไหม", "Tak"),
    ("อากาศเชียงใหม่วันนี้", "Chiang Mai"),
    ("อากาศ กทม. ร้อนไหม", "Bangkok"),
    ("อากาศกรุงเทพวันนี้", "Bangkok"),
    ("อุณหภูมิที่ภูเก็ต", "Phuket"),
    ("อากาศนครราชสีมา", "Nakhon Ratchasima"),
    ("อากาศที่อุบลราชธานี", "Ubon Ratchathani"),
    ("ฝนตกที่ประจวบคีรีขันธ์ไหม", "Prachuap Khiri Khan"),
])
def test_ได้เมืองที่ถาม(q, city):
    assert ws._extract_city(q) == city


@pytest.mark.parametrize("q", [
    "พรุ่งนี้ฝนตกไหม",
    "วันนี้ตากผ้าได้ไหม ฝนจะตกหรือเปล่า",     # ตาก = ตากผ้า
    "ฝนจะตกไหม บอกได้เลย",                   # เลย = ได้เลย
    "ข่าวเผยแพร่ว่าพายุเข้า อากาศเป็นยังไง",    # แพร่ = เผยแพร่
    "อากาศที่บ้านเป็นไงบ้าง",
])
def test_ไม่ระบุเมือง_หรือคำทั่วไป_ใช้เมืองบ้าน(q):
    assert ws._extract_city(q) == "HomeTown"


def test_ครบ_77_จังหวัด_ไม่ซ้ำ():
    assert len(ws._TH_PROVINCES) == 77
    assert len(set(ws._TH_PROVINCES.values())) == 77


def test_คำกำกวมเจอเป็นคำทั่วไปก่อน_ยังหาตำแหน่งถัดไป():
    assert ws._extract_city("เผยแพร่ข่าวว่าที่แพร่ฝนตกหนัก จริงไหม") == "Phrae"
    assert ws._extract_city("ตากผ้าไว้ แต่ที่ตากฝนตกไหม") == "Tak"


def test_ชื่อคล้ายกันได้จังหวัดถูกตัว():
    assert ws._extract_city("อากาศที่นครพนม") == "Nakhon Phanom"
    assert ws._extract_city("อากาศที่สระแก้ว") == "Sa Kaeo"
    assert ws._extract_city("อากาศที่สระบุรี") == "Saraburi"


def test_fetch_weather_ใช้เมืองที่สกัดได้(monkeypatch):
    seen = []
    monkeypatch.setattr(ws, "fetch_weather_by_city", lambda c: seen.append(c) or "ok")
    assert ws.fetch_weather("ที่แพร่ฝนตกไหม") == "ok"
    assert seen == ["Phrae"]


# ── ชื่อที่ส่งให้ wttr.in · วัดจริง 10-04 (ไล่ครบ 77 จังหวัด + ชื่อเรียกอื่น) ──
# ชื่อเปล่า: Nan → ฝรั่งเศส · Loei → ฝรั่งเศส · Tak → อัฟกานิสถาน
# "Nan, Thailand" (มีวรรค) → สระบุรี ✗ · "Nan,Thailand" → น่าน ✓ · ทุกจังหวัดห่างตัวเมือง ≤ 30 กม.
# ยกเว้น Surat Thani,Thailand → แถวระนอง ~82 กม. ⇒ ใช้พิกัดตัวเมือง
@pytest.mark.parametrize("city,loc", [
    ("Nan", "Nan,Thailand"),
    ("Loei", "Loei,Thailand"),
    ("Tak", "Tak,Thailand"),
    ("Phrae", "Phrae,Thailand"),
    ("phrae", "Phrae,Thailand"),           # agent อาจส่งตัวเล็ก
    ("Hat Yai", "Hat Yai,Thailand"),
    ("Surat Thani", "9.14,99.33"),
    ("Tokyo", "Tokyo"),                     # ต่างประเทศ — ไม่แตะ
    ("Chiang Mai, Thailand", "Chiang Mai, Thailand"),
])
def test_ชื่อที่ส่งให้_wttr(city, loc):
    assert ws._wttr_location(city) == loc


def test_fetch_weather_by_city_ยิงชื่อไทยแลนด์_แต่แสดงชื่อเมืองเดิม(monkeypatch):
    import requests
    seen = {}

    class R:
        status_code = 200
        text = '{"current_condition": [{"temp_C": "30"}], "weather": []}'

    def fake_get(url, **k):
        seen["url"] = url
        return R()

    monkeypatch.setattr(requests, "get", fake_get)
    out = ws.fetch_weather_by_city("Nan")
    assert seen["url"].startswith("https://wttr.in/Nan,Thailand?")
    assert "สภาพอากาศจริงของ Nan**" in out


# ── ป้ายวัน + เวลาสังเกตการณ์ (ต่อ 102) ──────────────────────────────────────────
# prod 10-04 21:4x น.: agent ตอบ "พรุ่งนี้ (4 ตุลาคม)" — tool ส่งวันที่ดิบ 2026-10-04/05/06
# โดยไม่บอกว่าวันไหนคือวันนี้ (agent ไม่รู้วันที่ปัจจุบัน) · "ปัจจุบัน ()" วงเล็บว่าง
# เพราะ wttr.in j1 ไม่มี localObsDateTime แล้ว (มีแต่ observation_time เป็น UTC)
def _fake_wttr(monkeypatch, body):
    import requests

    class R:
        status_code = 200
        text = body

    monkeypatch.setattr(requests, "get", lambda url, **k: R())


def test_พยากรณ์ติดป้าย_วันนี้_พรุ่งนี้_มะรืนนี้_ตามเวลาไทย(monkeypatch):
    import datetime as dt
    import json
    days = [{"date": d, "avgtempC": "25", "maxtempC": "30", "mintempC": "22", "sunHour": "5", "hourly": []}
            for d in ("2026-10-04", "2026-10-05", "2026-10-06")]
    _fake_wttr(monkeypatch, json.dumps({"current_condition": [{"temp_C": "24", "observation_time": "02:38 PM"}],
                                         "weather": days}))
    # 21:44 น. เวลาไทย = 14:44 UTC วันเดียวกัน
    monkeypatch.setattr(ws, "_now_bkk", lambda: dt.datetime(2026, 10, 4, 21, 44))
    out = ws.fetch_weather_by_city("Chiang Mai")
    assert "**2026-10-04 (วันนี้)**" in out
    assert "**2026-10-05 (พรุ่งนี้)**" in out
    assert "**2026-10-06 (มะรืนนี้)**" in out
    assert "()" not in out
    assert "21:38 น." in out                       # observation_time UTC → เวลาไทย


def test_ข้ามเที่ยงคืนเวลาไทย_ป้ายเลื่อนตาม(monkeypatch):
    import datetime as dt
    import json
    days = [{"date": d, "hourly": []} for d in ("2026-10-04", "2026-10-05")]
    _fake_wttr(monkeypatch, json.dumps({"current_condition": [{}], "weather": days}))
    monkeypatch.setattr(ws, "_now_bkk", lambda: dt.datetime(2026, 10, 5, 0, 30))
    out = ws.fetch_weather_by_city("Phrae")
    assert "**2026-10-04 (เมื่อวาน)**" not in out and "**2026-10-04**" in out
    assert "**2026-10-05 (วันนี้)**" in out
    assert "()" not in out                         # ไม่มีเวลาสังเกตการณ์ = ไม่มีวงเล็บ
