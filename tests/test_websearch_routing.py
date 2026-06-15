"""Weather short-circuit ต้องไม่แย่งคำถามที่แค่บังเอิญมีคำบอกเวลา

ทำไมสำคัญ: บั๊กจริง (เจอ 2026-06-15) — `_WEATHER_KEYWORDS` รวม `วันนี้|พรุ่งนี้`
ซึ่งเป็นคำบอกเวลา ไม่ใช่คำเกี่ยวกับอากาศ → คำถามอย่าง "ราคาทองวันนี้"/"ข่าววันนี้"
โดน route ไป fetch_weather() แล้วคืนพยากรณ์อากาศ ไม่เคยไปถึง Google search เลย
(ทำให้ web-search grounding ใช้ไม่ได้กับทุกคำถามที่มี "วันนี้")
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import websearch


class TestWeatherRouting:
    def test_temporal_word_alone_is_not_weather(self):
        """คำถามที่มีแค่คำบอกเวลา (ไม่มีคำอากาศ) ต้องไม่ route ไป weather"""
        for q in [
            "ราคาทองวันนี้เท่าไหร่",
            "ข่าวการเมืองวันนี้",
            "พรุ่งนี้มีประชุมกี่โมง",
            "หุ้นวันนี้ขึ้นหรือลง",
        ]:
            assert websearch._WEATHER_KEYWORDS.search(q) is None, (
                f"{q!r} ถูก route ไป weather ผิด (แค่มีคำบอกเวลา)"
            )

    def test_real_weather_queries_still_match(self):
        """คำถามอากาศจริงต้องยัง route ไป weather ได้"""
        for q in [
            "วันนี้อากาศเป็นยังไง",
            "พรุ่งนี้ฝนตกไหม",
            "อุณหภูมิตอนนี้กี่องศา",
            "พยากรณ์อากาศกรุงเทพ",
            "weather in Bangkok today",
        ]:
            assert websearch._WEATHER_KEYWORDS.search(q) is not None, (
                f"{q!r} ควร route ไป weather แต่ไม่ match"
            )
