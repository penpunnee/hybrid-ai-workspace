"""เลือกหน้าที่จะ fetch จากความตรงคำถาม ไม่ใช่ลำดับของ provider (2026-10-05)

ของจริง (prod 10-04 23:46 โหมดเสียง · "ผู้กล้าเหนือกาลเวลา … เผ่าเงือก ตอนที่"):
เดิม fetch 3 ผลแรก *ตามลำดับ Brave* (YouTube/Facebook) แล้วค่อย rerank ⇒ ผลที่ชนะ rerank
(หน้านิยาย) ไม่เคยถูก fetch · fetched_text = 0 · ขวัญได้ snippet บรรทัดเดียวแล้วตอบ "ไม่เจอ"
ยิงซ้ำบน prod: pre-rank ด้วย title+snippet เลือกหน้านิยาย 3 หน้า · Python → python.org ติด top 3
แต่ "ราคาทองวันนี้" ทำ goldtraders.or.th (Brave #1-3) หลุด ⇒ เก็บอันดับ 1 ของ provider ไว้ด้วยเสมอ

ระบบอื่นทำแบบเดียวกัน: ค้น → จัดอันดับ → ค่อย fetch อันดับต้น (vault: llm-web-search-pipeline-settings)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import websearch  # noqa: E402

# ผลจาก provider: อันดับต้นไม่เกี่ยว · หน้าที่ตรงอยู่ท้าย
_PROVIDER = [
    {"title": "วิดีโอรวม", "body": "เพลย์ลิสต์", "href": "https://video.example/1"},
    {"title": "โพสต์เพจ", "body": "แชร์", "href": "https://social.example/2"},
    {"title": "หน้าแรกเว็บ", "body": "ยินดีต้อนรับ", "href": "https://home.example/3"},
    {"title": "ตรง บทที่ 130 เผ่าเงือก", "body": "ตรง", "href": "https://novel.example/4"},
    {"title": "ตรง สารบัญตอน", "body": "ตรง", "href": "https://novel.example/5"},
    {"title": "ตรง เรื่องย่อ", "body": "ตรง", "href": "https://novel.example/6"},
]


def _fake_rerank(query, items, text_keys=("title",), top_k=3, **_):
    """คะแนนจาก text_keys จริง — ใส่ "ตรง" ใน fetched_text ก็ได้คะแนนเพิ่ม (เหมือน embed)"""
    out = []
    for it in items:
        text = " ".join(str(it.get(k, "")) for k in text_keys)
        out.append({**it, "_rerank_score": 0.4 + 0.1 * min(text.count("ตรง"), 5)})
    out.sort(key=lambda r: -r["_rerank_score"])
    return out[:top_k]


def _setup(monkeypatch, fetched):
    monkeypatch.setattr(websearch, "search_web", lambda *a, **k: [dict(r) for r in _PROVIDER])
    monkeypatch.setattr("utils.embed.rerank_by_similarity", _fake_rerank)
    monkeypatch.setattr("utils.query_rewrite.rewrite_query",
                        lambda q: type("R", (), {"all_queries": [q], "used_llm": False, "rewritten": q,
                                                 "sub_queries": []})())

    def fetch(url):
        fetched.append(url)
        return f"เนื้อหาเต็มจาก {url} ตรง ตรง"
    monkeypatch.setattr(websearch, "_fetch_url", fetch)


def _assert_picks(fetched):
    assert {"https://novel.example/4", "https://novel.example/5", "https://novel.example/6"} <= set(fetched), \
        f"หน้าที่ตรงคำถามไม่ถูก fetch: {fetched}"
    assert "https://video.example/1" in fetched, "อันดับ 1 ของ provider ต้องถูก fetch ด้วยเสมอ"
    assert len(fetched) <= 4, f"fetch {len(fetched)} หน้า (เพดาน 4)"


def test_แชท_fetch_หน้าที่ตรงคำถาม_ไม่ใช่ลำดับ_provider(monkeypatch):
    fetched = []
    _setup(monkeypatch, fetched)
    ctx, results, status = websearch._web_search_impl("เผ่าเงือก ตอนที่", max_results=5, top_k=3)
    _assert_picks(fetched)
    assert status == "ok" and "เนื้อหาเต็มจาก https://novel.example/4" in ctx


def test_agent_fetch_หน้าที่ตรงคำถาม_ไม่ใช่ลำดับ_provider(monkeypatch):
    from agents import tools as agent_tools
    fetched = []
    _setup(monkeypatch, fetched)
    out = agent_tools._t_web_search("เผ่าเงือก ตอนที่")
    _assert_picks(fetched)
    assert "เนื้อหาเต็มจาก https://novel.example/4" in out


def test_ผลน้อยกว่าเพดาน_fetch_ครบทุกผล(monkeypatch):
    fetched = []
    monkeypatch.setattr(websearch, "_fetch_url", lambda u: fetched.append(u) or "x")
    monkeypatch.setattr("utils.embed.rerank_by_similarity", _fake_rerank)
    websearch._select_and_fetch([dict(r) for r in _PROVIDER[:2]], "q")
    assert sorted(fetched) == ["https://social.example/2", "https://video.example/1"]


def test_จัดอันดับล่วงหน้าล้ม_ใช้ลำดับ_provider_ไม่ล้มทั้งก้อน(monkeypatch):
    fetched = []
    monkeypatch.setattr(websearch, "_fetch_url", lambda u: fetched.append(u) or "x")

    def boom(*a, **k):
        raise RuntimeError("embed ล่ม")
    monkeypatch.setattr("utils.embed.rerank_by_similarity", boom)
    out = websearch._select_and_fetch([dict(r) for r in _PROVIDER], "q")
    assert sorted(fetched) == sorted(r["href"] for r in _PROVIDER[:3])
    assert len(out) == 6, "ล้มแล้วต้องคืนผลทั้งหมดให้ rerank รอบสุดท้ายตัดสินเหมือนเดิม"


# ── โหมดเสียง: ผลค้นตอบได้บางส่วน → บอกสิ่งที่ใกล้ที่สุดพร้อมที่มา ไม่โยนคำถามกลับ ──
# prod 10-04 23:46–23:57: ขวัญตอบ "ไม่เจอ ช่วยบอกรายละเอียดเพิ่ม" 5 ครั้งติด ทั้งที่ผลมี
# "บทที่ 130 … เผ่าเงือก" · user: "ก็รู้รายละเอียดในนิยายตอนนั้นน่ะสิ ไม่ใช่มาถามต่ออย่างนี้"
# คำสั่งเดิมมีแต่ "ห้ามเดา" (สั่งสิ่งที่ห้าม) ไม่บอกว่าข้อมูลมีบางส่วนให้ทำอะไร

def test_คำสั่งเสียง_มีกรณีตอบได้บางส่วน_และไม่ถามกลับ():
    g = websearch.VOICE_SEARCH_GUIDE
    assert "ใกล้ที่สุด" in g, "ต้องสั่งให้บอกข้อมูลที่ใกล้คำถามที่สุดที่เจอ"
    assert "ถามกลับ" in g, "ต้องสั่งไม่ให้โยนคำถามกลับไปที่ผู้ใช้"
    assert "ห้ามเดา" in g, "ตัวกันการแต่งชื่อ/ตัวเลขเดิมต้องอยู่"
