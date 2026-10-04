"""เนื้อหาจากหน้าเว็บต้องเป็น "ส่วนที่ตอบคำถาม" ไม่ใช่เมนูเว็บ (prod 2026-10-04 ต่อ 100)

ของจริง: ถาม agent "หวังหลินออกจากแดนอัสนีแล้วเนื้อเรื่องเป็นยังไง" → ได้แต่เรื่องย่อหน้าปก
- fetch reeeed.com (เว็บ JS) ได้ชื่อเรื่อง 26 ตัวอักษร แต่ป้ายบอก "ถูกตัดท้าย" ⇒ โมเดลเปิดซ้ำ เสีย 2/4 รอบ
- ชื่อเรื่อง 26 ตัวอักษรนั้นยังไปแทน snippet ของ Brave ที่มีเรื่องย่อ (format_for_context เลือก fetched เสมอ)
- Dek-D/Pantip/Fandom: 2,500 ตัวแรกเป็นปุ่ม Sign In/แชร์ — Fandom มีเนื้อเรื่อง Thunder Celestial Realm
  แต่อยู่ลึกในหน้า 76k ตัวอักษร ตัดหัวหน้าไม่มีวันถึง ⇒ ต้องเลือกช่วงที่ตรงคำค้น
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import urlguard, websearch  # noqa: E402

_CHROME = "Sign In Create a Free Account Advertisement Skip to content แชร์ไปยังเฟซบุ๊ก ตั้งรหัสผ่าน " * 20


def _filler(n):
    return "".join(f"ย่อหน้าทั่วไปลำดับ {i} เกี่ยวกับตัวละครและการฝึกฝน " for i in range(n))


# ── _extract_text: เนื้อหาหลัก + คำอธิบายหน้าเมื่อเนื้อหาว่าง ───────────────────

def test_มี_main_ที่มีเนื้อหา_ใช้แค่ใน_main_ทิ้งเมนูรอบนอก():
    body = "เนื้อเรื่องหลักของหน้า " * 60
    html = f"<html><body><div class='topbar'>{_CHROME}</div><main>{body}</main><div>{_CHROME}</div></body></html>"
    text = websearch._extract_text(html)
    assert text.startswith("เนื้อเรื่องหลักของหน้า")
    assert "Sign In" not in text


def test_main_ว่างหรือสั้น_ใช้ทั้งหน้าเหมือนเดิม():
    html = f"<html><body><main><div id='app'></div></main><p>{'เนื้อหานอก main ' * 50}</p></body></html>"
    assert "เนื้อหานอก main" in websearch._extract_text(html)


def test_หน้า_JS_เนื้อหาว่าง_ใช้_og_description():
    html = ('<html><head><meta property="og:description" content="หวังหลิน ชายหนุ่มผู้ค้นพบหนทางการฝึกเซียน">'
            '</head><body><main><div id="__next"></div></main><h1>ฝืนลิขิตฟ้า</h1></body></html>')
    text = websearch._extract_text(html)
    assert "หวังหลิน ชายหนุ่มผู้ค้นพบหนทางการฝึกเซียน" in text


# ── focus_passages: เลือกช่วงที่ตรงคำค้น ────────────────────────────────────

def test_ช่วงที่ตรงคำค้นอยู่ลึก_ต้องติดมา_และไม่เกินเพดาน():
    deep = "Wang Lin helped the clan leave the Thunder Celestial Realm and killed the Yao family. "
    text = "Wang Lin " + _CHROME + _filler(300) + deep + _filler(300)
    out = websearch.focus_passages(text, "Wang Lin Thunder Celestial Realm Yao", 2500)
    assert "Thunder Celestial Realm" in out
    assert len(out) <= 2500 + 50          # ตัวคั่น " … " ระหว่างช่วง


def test_คำที่มีทุกช่วง_ไม่ดึงช่วงมั่ว():
    """'Wang Lin' อยู่เกือบทุกย่อหน้า — ช่วงที่มีแค่ชื่อตัวเอก 2 คำต้องแพ้ช่วงที่มีคำหายาก 1 คำ
    (นับจำนวนคำเฉยๆ ช่วง Wang Lin ได้ 2 ชนะ Thunder ได้ 1 → ได้ย่อหน้ามั่ว)"""
    common = "Wang Lin practiced his cultivation art again today. ".ljust(100, ".")
    rare = "The clan finally escaped from the Thunder realm gate. ".ljust(100, ".")
    text = common * 20 + rare + common * 20       # ช่วงละ 100 พอดี — ช่วง Thunder ไม่มี Wang Lin
    out = websearch.focus_passages(text, "Wang Lin Thunder", 100, window=100)
    assert "Thunder" in out


def test_ไม่มีคำค้น_หรือไม่ตรงเลย_ตัดหัวหน้าแบบเดิม():
    text = _filler(500)
    assert websearch.focus_passages(text, "", 1000) == text[:1000]
    assert websearch.focus_passages(text, "ไม่มีคำนี้ในหน้า", 1000) == text[:1000]


def test_หน้าสั้นกว่าเพดาน_คืนทั้งหน้า():
    assert websearch.focus_passages("สั้นๆ", "อะไรก็ได้", 1000) == "สั้นๆ"


def test_enrich_ส่งคำค้นแล้วได้ช่วงที่เกี่ยว(monkeypatch):
    deep = "หลังออกจากแดนอัสนี หวังหลินกลับไปดาวซูเชว่ "
    long_text = _CHROME + _filler(400) + deep + _filler(400)
    monkeypatch.setattr(websearch, "_fetch_url", lambda u: long_text)
    out = websearch._enrich_with_fetch(
        [{"title": "t", "body": "b", "href": "https://x.example/a"}], query="หวังหลิน แดนอัสนี")
    assert "แดนอัสนี" in out[0]["fetched_text"]
    assert len(out[0]["fetched_text"]) <= websearch._FETCH_MAX_CHARS + 50


# ── format_for_context: เนื้อหาที่ดึงได้สั้นกว่า snippet = ใช้ snippet ────────────

def test_ดึงได้แค่ชื่อเรื่อง_ใช้_snippet_ที่ยาวกว่า():
    results = [{"title": "ฝืนลิขิตฟ้า", "href": "https://reeeed.example/n",
                "body": "หวังหลินมุ่งมั่นไม่ย่อท้อ หลังล้มเหลวกลับมาจึงอยากจะทดสอบอีกครั้ง",
                "fetched_text": "ฝืนลิขิตฟ้า ข้าขอเป็นเซียน"}]
    ctx = websearch.format_for_context(results, "q")
    assert "หวังหลินมุ่งมั่นไม่ย่อท้อ" in ctx


# ── tool fetch_url: บอกตรงๆ เมื่ออ่านไม่ได้ · focus ────────────────────────────

def _html_result(html):
    return lambda url, **k: urlguard.FetchResult(url=url, content_type="text/html", text=html, truncated=False)


def test_fetch_url_หน้า_JS_บอกว่าอ่านไม่ได้_ไม่ใช่ถูกตัดท้าย(monkeypatch):
    from agents import tools as agent_tools
    html = "<html><script>" + "x" * 20000 + "</script><h1>ฝืนลิขิตฟ้า ข้าขอเป็นเซียน</h1></html>"
    monkeypatch.setattr(urlguard, "fetch_url_safe", _html_result(html))
    out = agent_tools._t_fetch_url("https://reeeed.example/n")
    assert "ถูกตัดท้าย" not in out
    assert "อ่านเนื้อหาไม่ได้" in out and "ห้ามเปิดหน้านี้ซ้ำ" in out


def test_fetch_url_หน้ายาวจริง_ยังบอกว่าถูกตัด(monkeypatch):
    from agents import tools as agent_tools
    monkeypatch.setattr(urlguard, "fetch_url_safe", _html_result(f"<p>{_filler(400)}</p>"))
    out = agent_tools._t_fetch_url("https://x.example/a")
    assert "ถูกตัดท้าย" in out or "เฉพาะช่วง" in out
    assert "อ่านเนื้อหาไม่ได้" not in out


def test_fetch_url_focus_ได้ย่อหน้าที่อยู่ลึก(monkeypatch):
    from agents import tools as agent_tools
    deep = "Wang Lin helped the Chosen Immortal Clan out of the Thunder Celestial Realm. "
    monkeypatch.setattr(urlguard, "fetch_url_safe",
                        _html_result(f"<main><p>{_filler(500)}{deep}{_filler(500)}</p></main>"))
    out = agent_tools._t_fetch_url("https://wiki.example/Wang_Lin", focus="Thunder Celestial Realm")
    assert "Chosen Immortal Clan" in out


def test_registry_fetch_url_มี_focus_ไม่บังคับ_และ_web_search_แนะค้นอังกฤษ():
    from agents.tools import _ALL_TOOLS
    fu = _ALL_TOOLS["fetch_url"]["parameters"]
    assert "focus" in fu["properties"] and fu["required"] == ["url"]
    assert "อังกฤษ" in _ALL_TOOLS["web_search"]["description"]


# ── ทั้งสอง pipeline ต้องส่งคำค้นเข้า enrich จริง (CLAUDE.md: ค้นเว็บมี 2 เส้น แก้ต้องแก้คู่) ──

def _capture_enrich(monkeypatch, seen):
    def fake(results, **k):
        seen.append(k.get("query"))
        return results
    monkeypatch.setattr(websearch, "_enrich_with_fetch", fake)
    good = [{"title": "t", "body": "เนื้อหา", "href": "https://x.example/a", "_rerank_score": 0.9}]
    monkeypatch.setattr(websearch, "search_web", lambda *a, **k: [dict(r) for r in good])
    monkeypatch.setattr("utils.embed.rerank_by_similarity", lambda q, rs, **k: rs)


def test_agent_web_search_ส่งคำค้นให้_enrich(monkeypatch):
    from agents import tools as agent_tools
    seen = []
    _capture_enrich(monkeypatch, seen)
    agent_tools._t_web_search("Renegade Immortal Thunder Celestial Realm")
    assert seen == ["Renegade Immortal Thunder Celestial Realm"]


def test_แชท_web_search_ส่งคำค้นให้_enrich(monkeypatch):
    seen = []
    _capture_enrich(monkeypatch, seen)
    websearch._web_search_impl("Renegade Immortal Thunder Celestial Realm", max_results=5, top_k=3)
    assert seen and seen[0], f"ไม่ได้ส่งคำค้น: {seen}"


# ── คำแนะนำค้นอังกฤษต้องอยู่ใน "ผลของ tool" (prod วัดซ้ำ 2/2: คำแนะนำใน description ไม่มีผล
#    qwen ค้นไทยรอบเดียวแล้วตอบ "ไม่พบ" — โมเดลเล็กตัดสินใจรอบถัดไปจากผลที่เพิ่งได้) ──

def test_ผลค้นภาษาไทย_แนะให้ค้นซ้ำภาษาอังกฤษ(monkeypatch):
    from agents import tools as agent_tools
    _capture_enrich(monkeypatch, [])
    out = agent_tools._t_web_search("ฝืนลิขิตฟ้า หวังหลิน ออกจากแดนอัสนี")
    assert "ภาษาอังกฤษ" in out and "web_search" in out


def test_ผลค้นภาษาอังกฤษ_ไม่มีคำแนะนำซ้ำ(monkeypatch):
    from agents import tools as agent_tools
    _capture_enrich(monkeypatch, [])
    out = agent_tools._t_web_search("Renegade Immortal Thunder Celestial Realm")
    assert "ค้นซ้ำเป็นภาษาอังกฤษ" not in out
