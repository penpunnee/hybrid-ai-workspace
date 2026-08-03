"""พื้นคะแนนสัมบูรณ์ของ web search — ห้ามฉีด/อ้างอิงผลที่พิสูจน์ความเกี่ยวข้องไม่ได้

**เคสจริงที่ทำให้ต้องมีไฟล์นี้ (prod `req_e2bb0655`, 2026-08-03):**
ถาม *"Python เวอร์ชันเสถียรล่าสุดคืออะไร"* → Gemini quota 429 → fallback ไป local + web search
→ `search_web()` ได้ prompt ดิบทั้งประโยคเป็นคำค้น → Google CSE ว่าง → DDG `region=th-th`
→ ได้เว็บสแปมไทย **รวมเว็บโป๊** แล้วถูกฉีดเข้า context ของโมเดล *และ* เรนเดอร์ขึ้นจอเป็น citation `[1] [3]`

ตอนนั้น `utils/websearch.py` **จัดอันดับอย่างเดียว ไม่เคยตัดทิ้ง** — หลัง rerank คือ `results[:top_k]`
ตรงๆ ไม่มีเกณฑ์คะแนนขั้นต่ำเลยทั้งไฟล์ · `safesearch="on"` ที่ตั้งไว้พร้อมคอมเมนต์ว่า
"กัน NSFW ที่ต้นทาง" ก็ไม่ได้กันจริง (เจตนา ไม่ใช่หลักฐาน)

**ที่มาของเลข 0.35** — วัดจริงในคอนเทนเนอร์ prod 2026-08-03 (4 query):

| กลุ่ม | คะแนนที่วัดได้ |
|---|---|
| ผลถูกต้อง (`Python latest stable version`, `Synology DS923+ specs`) | 0.5955 – 0.8234 |
| ขยะทั้งหมด (รวมเคสโป๊ + `ราคาทองคำวันนี้` ที่ค้นไทยแล้วพัง) | 0.1024 – 0.2393 |

ช่องว่าง **0.36** = "ที่ราบกว้าง" → เชื่อเกณฑ์ได้ (เกณฑ์วัดจากที่ราบ ไม่ใช่จากค่า F1)
0.35 อยู่เหนือขยะสูงสุด 0.11 และต่ำกว่าผลดีที่แย่สุด 0.245 · เลขเดียวกับ
`SKILLS_FALLBACK_MIN_SCORE` ที่ใช้อยู่แล้วในโปรเจกต์
"""

from utils import websearch


def _res(score, title="ผลลัพธ์", url="https://example.com"):
    return {"title": title, "href": url, "body": "เนื้อหา", "_rerank_score": score}


class TestMinScoreFloor:
    def test_garbage_scores_are_dropped(self):
        """คะแนนที่วัดได้จริงจากเคสโป๊ (0.1874 / 0.1292 / 0.1844) ต้องไม่ผ่าน"""
        kept = websearch._drop_below_min_score([
            _res(0.1874, "หนังโป๊เก่าเก็บ", "https://th.gratisreifefrauen.com/"),
            _res(0.1292, "แจ็ค The Ghost | หม่ำกับหม่ำ", "https://www.youtube.com/x"),
            _res(0.1844, "หนังโป๊ญี่ปุ่น WAAA-557"),
        ])
        assert kept == [], f"ผลคะแนนต่ำยังหลุดผ่าน: {[r['title'] for r in kept]}"

    def test_good_scores_pass(self):
        """คะแนนที่วัดได้จริงจากผลที่ถูกต้องต้องผ่านครบ"""
        good = [_res(0.8234, "The Latest Version of Python"),
                _res(0.6579, "Python Releases | Python.org"),
                _res(0.5955, "Synology DS923+ Review")]
        assert websearch._drop_below_min_score(good) == good

    def test_boundary_is_inclusive(self):
        """ที่เกณฑ์พอดีให้ผ่าน — กันเส้นแบ่งกำกวมเวลาปรับค่า"""
        floor = websearch.WEB_SEARCH_MIN_SCORE
        assert websearch._drop_below_min_score([_res(floor)]) != []
        assert websearch._drop_below_min_score([_res(floor - 0.001)]) == []

    def test_unscored_results_are_dropped(self):
        """ไม่มีคะแนน = พิสูจน์ความเกี่ยวข้องไม่ได้ = ไม่ฉีด

        เกิดตอน rerank ล้ม (embed service ล่ม) แล้วโค้ดตกไปทาง `results[:top_k]`
        **ตัดสินใจให้ fail-closed**: หน้าที่ของพื้นคะแนนคือ "พิสูจน์ก่อนฉีด" —
        ผลที่ไม่มีคะแนนคือผลที่ยังไม่ถูกพิสูจน์ ถ้าปล่อยผ่านรูเดิมจะยังเปิดอยู่
        ทั้งดุ้น (เคสโป๊จะกลับมาทันทีที่ embed ล่ม)
        แลกกับ: embed ล่ม = web search เงียบไปเลย → ปิดพื้นชั่วคราวด้วย
        `WEB_SEARCH_MIN_SCORE=off` ได้ถ้าจำเป็น
        """
        assert websearch._drop_below_min_score([_res(None), _res(None)]) == []

    def test_can_be_disabled(self):
        """ต้องปิดได้โดยไม่ต้องแก้โค้ด (เผื่อ embed ล่มยาว)"""
        assert websearch._drop_below_min_score([_res(0.01), _res(None)], min_score=None) != []


class TestNoContextWhenEverythingIsGarbage:
    """ทั้งหมดตกเกณฑ์ → ต้องเงียบ ไม่ใช่ยัดขยะ

    "ไม่รู้" ต้องไม่หน้าตาเหมือน "รู้" — ถ้าไม่มีผลที่เชื่อได้ ให้ context ว่าง
    เพื่อให้โมเดลบอกว่าหาไม่เจอ ดีกว่าให้มันสรุปจากเว็บโป๊
    """

    def test_impl_returns_empty_when_all_below_floor(self, monkeypatch):
        junk = [_res(0.18, "หนังโป๊เก่าเก็บ"), _res(0.12, "คลิปหลุด")]
        monkeypatch.setattr(websearch, "search_web", lambda *a, **k: junk)
        monkeypatch.setattr(websearch, "_enrich_with_fetch", lambda r, **k: r)
        monkeypatch.setattr("utils.embed.rerank_by_similarity", lambda *a, **k: junk)

        ctx, results = websearch._web_search_impl("Python เวอร์ชันล่าสุด", max_results=5, top_k=3)

        assert results == [], f"ยังคืนผลขยะออกไปให้ citation: {results}"
        assert ctx == "", f"ยังฉีด context จากผลขยะ: {ctx[:200]!r}"


class TestAgentToolHasTheSameFloor:
    """`agents/tools.py:_t_web_search` เป็น pipeline ซ้ำอีกชุด — ต้องมีพื้นเดียวกัน

    ตอนเจอบั๊กมันคัดลอก search→enrich→rerank→format มาทั้งชุดโดยไม่มีทั้ง domain score
    และพื้นคะแนน · agent mode คือเส้นที่ CLAUDE.md แนะนำให้ใช้เวลาต้องการความถูกต้อง
    เป๊ะ ๆ ถ้าปล่อยไว้ก็ปิดรูแค่ครึ่งเดียว
    """

    def test_agent_tool_drops_garbage(self, monkeypatch):
        from agents import tools as agent_tools

        junk = [_res(0.18, "หนังโป๊เก่าเก็บ"), _res(0.12, "คลิปหลุด")]
        monkeypatch.setattr(websearch, "search_web", lambda *a, **k: junk)
        monkeypatch.setattr(websearch, "_enrich_with_fetch", lambda r, **k: r)
        monkeypatch.setattr("utils.embed.rerank_by_similarity", lambda *a, **k: junk)

        out = agent_tools._t_web_search("Python เวอร์ชันล่าสุด")

        assert "หนังโป๊" not in out, f"agent tool ยังคืนผลขยะให้โมเดล: {out[:200]!r}"
        assert out.strip() != "", "ควรบอกว่าหาไม่เจอ ไม่ใช่คืนสตริงว่างเปล่าลอยๆ"

    def test_agent_tool_keeps_good_results(self, monkeypatch):
        from agents import tools as agent_tools

        good = [_res(0.82, "The Latest Version of Python", "https://python.org/x")]
        monkeypatch.setattr(websearch, "search_web", lambda *a, **k: good)
        monkeypatch.setattr(websearch, "_enrich_with_fetch", lambda r, **k: r)
        monkeypatch.setattr("utils.embed.rerank_by_similarity", lambda *a, **k: good)

        assert "Latest Version of Python" in agent_tools._t_web_search("Python latest version")


class TestSafesearchIsActuallyRequested:
    """`safesearch='on'` ต้องถูกส่งถึง DDG จริง ไม่ใช่แค่เขียนไว้ใน default

    (คุมได้แค่ว่า "เราขอไป" — ว่า DDG กรองให้จริงไหมคุมไม่ได้ จึงต้องมีพื้นคะแนนเป็นด่านที่สอง)
    """

    def test_ddg_called_with_safesearch_on(self, monkeypatch):
        captured = {}

        class FakeDDGS:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def text(self, *args, **kwargs):
                captured.update(kwargs)
                return []

        import sys, types
        fake = types.ModuleType("ddgs")
        fake.DDGS = FakeDDGS
        monkeypatch.setitem(sys.modules, "ddgs", fake)

        websearch._ddg_search("test", max_results=3)
        assert captured.get("safesearch") == "on", f"ไม่ได้ส่ง safesearch ไป DDG: {captured}"
