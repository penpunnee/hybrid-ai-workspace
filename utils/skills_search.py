"""
Skills Search - Semantic Search using ChromaDB for Skills
ทำให้ AI สามารถค้นหาและใช้ skills ที่เกี่ยวข้องกับคำถามได้
"""
import logging
import threading
from typing import List, Dict, Optional
import chromadb

from core.config import CHROMA_HOST as _CFG_CHROMA_HOST
from core.config import CHROMA_PORT as _CFG_CHROMA_PORT
from utils.memory import get_or_create_collection

logger = logging.getLogger(__name__)


def _embed_model_tag() -> str:
    """ป้ายโมเดล embed ที่เก็บใน metadata — เปลี่ยน EMBEDDING_MODEL แล้ว sync ต้อง re-embed (vector คนละ space)
    อ่านจาก core.config ตอนเรียก (ไม่ผูกตอน import) · "" = ปิด EF ของเรา → chroma ใช้ default ของมัน (utils/memory.py)"""
    from core import config
    return config.EMBEDDING_MODEL or "default"


def _skill_entry(topic: str, summary: str, category: str, source: str) -> tuple[str, dict]:
    """document + metadata ของ skill หนึ่งตัว — ที่เดียวที่กำหนดรูป (add_skill กับ sync ต้องเทียบกันได้เป๊ะ)"""
    return f"{topic}: {summary}", {"topic": topic, "category": category, "source": source,
                                   "embed_model": _embed_model_tag()}


def _upsert_changed(collection, skill_id, skills_db: Dict, current: Dict) -> tuple[int, int]:
    """upsert เฉพาะตัวที่ document/metadata ต่างจากที่ index มี — **ครั้งเดียวทั้งชุด** (EF ส่ง list ใน embed เดียว)
    batch ล้ม → ถอยทีละตัว (ตัวเสียตัวเดียวไม่ลากทั้งชุด = พฤติกรรมเดิม) · คืน (จำนวนที่เปลี่ยน, จำนวนที่ upsert สำเร็จ)"""
    ids, docs, metas = [], [], []
    for topic, data in skills_db.items():
        doc, meta = _skill_entry(topic, data.get("summary", ""), "learned", data.get("source", "unknown"))
        sid = skill_id(topic)
        if current.get(sid) == (doc, meta):
            continue
        ids.append(sid)
        docs.append(doc)
        metas.append(meta)
    if not ids:
        return 0, 0
    try:
        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        return len(ids), len(ids)
    except Exception as e:
        logger.warning(f"sync_from_db: upsert ทั้งชุด {len(ids)} รายการล้ม ({e}) — ถอยไปทีละตัว")
    done = 0
    for sid, doc, meta in zip(ids, docs, metas):
        try:
            collection.upsert(ids=[sid], documents=[doc], metadatas=[meta])
            done += 1
        except Exception as e:
            logger.error(f"Failed to upsert skill {meta['topic']}: {e}")
    return len(ids), done


class SkillsSearch:
    """Semantic Search สำหรับ Skills โดยใช้ ChromaDB"""
    
    def __init__(self, chroma_host: Optional[str] = None, chroma_port: Optional[int] = None):
        """
        Initialize Skills Search with ChromaDB
        
        Args:
            chroma_host: ChromaDB host (default from env or localhost)
            chroma_port: ChromaDB port (default from env or 8000)
        """
        # ค่าจาก config (เจ้าของ CHROMA_*) — config default "" จึง `or "localhost"` เท่าเดิม (ก้อน 4 · 2026-09-24)
        self.chroma_host = chroma_host or (_CFG_CHROMA_HOST or "localhost")
        self.chroma_port = chroma_port or _CFG_CHROMA_PORT
        
        # Initialize ChromaDB client
        try:
            self.client = chromadb.HttpClient(
                host=self.chroma_host,
                port=self.chroma_port
            )
            self.collection_name = "skills_collection"

            # ⚠️ ต้องผ่าน `get_or_create_collection()` เท่านั้น — เดิมเรียก
            # `client.create_collection()` ตรงๆ จึงไม่ได้ `hnsw:space: cosine` ติดมาด้วย
            # (chroma default = l2 ซึ่ง distance ไม่มีขอบบน) → เทียบเกณฑ์กับเส้นอื่น
            # ในโปรเจกต์ไม่ได้ และ `1.0 - distance` ที่ skills_shadow.py ใช้ก็แปลผลผิด
            self.collection = get_or_create_collection(
                self.client,
                self.collection_name,
                metadata={"description": "Skills Semantic Search", "hnsw:space": "cosine"},
            )
            logger.info(f"Skills search ready: {self.collection_name}")

            self.available = True
        except Exception as e:
            logger.warning(f"Skills search initialization failed: {e}")
            self.available = False
            self.collection = None
    
    def add_skill(self, topic: str, summary: str, category: str = "general", source: str = "unknown"):
        """
        Add a skill to the search index
        
        Args:
            topic: Skill topic/name
            summary: Skill summary/description
            category: Skill category (e.g., python, docker, git)
            source: Source of the skill
        """
        if not self.available or not self.collection:
            logger.warning("Skills search not available, skipping add_skill")
            return
        
        try:
            skill_id = f"skill_{topic.replace(' ', '_').lower()}"
            doc, meta = _skill_entry(topic, summary, category, source)
            self.collection.upsert(ids=[skill_id], documents=[doc], metadatas=[meta])
            logger.info(f"Upserted skill: {topic}")
        except Exception as e:
            logger.error(f"Failed to upsert skill: {e}")
    
    def add_skills_from_db(self, skills_db: Dict):
        """
        Add all skills from skills_db.json to the search index
        
        Args:
            skills_db: Dictionary of skills from skills_db.json
        """
        if not self.available or not self.collection:
            logger.warning("Skills search not available, skipping add_skills_from_db")
            return
        
        for topic, data in skills_db.items():
            self.add_skill(
                topic=topic,
                summary=data.get("summary", ""),
                category="learned",
                source=data.get("source", "unknown")
            )

    @staticmethod
    def _skill_id(topic: str) -> str:
        """id scheme เดียวกับ add_skill() — แยกออกมาให้ sync ใช้ร่วมได้"""
        return f"skill_{topic.replace(' ', '_').lower()}"

    def sync_from_db(self, skills_db: Dict):
        """sync จริง = upsert ของที่มี + **ลบของที่หายไปจาก skills_db**

        เดิม `add_skills_from_db()` มีแต่ upsert ไม่เคยลบ → ลบ skill ออกจาก
        skills_db.json แล้วมันยังค้างใน ChromaDB ตลอดไป และยังถูกดึงเข้า context
        ต่อ (เจอจริง 2026-08-02 ตอนล้าง Dream skills: ไฟล์เหลือ 52 แต่ index 128)
        """
        if not self.available or not self.collection:
            logger.warning("Skills search not available, skipping sync_from_db")
            return
        # get() คืน documents+metadatas เป็นค่า default (chromadb 1.5.9 Collection.py:136) → ใช้ข้ามตัวที่ไม่เปลี่ยน
        # เดิม upsert ทีละตัวทุกบูต = embed 22 ครั้ง 34–55 วิ แย่งคิวกับ recall (agent step แรกช้า 19 วิ · วัด prod 09-28/29)
        current: Dict = {}
        try:
            got = self.collection.get()
            existing = set(got.get("ids", []) or [])
            ids = got.get("ids") or []
            docs = got.get("documents") or [None] * len(ids)
            metas = got.get("metadatas") or [None] * len(ids)
            current = {i: (d, m) for i, d, m in zip(ids, docs, metas)}
        except Exception as e:
            logger.warning(f"sync_from_db: อ่าน index เดิมไม่ได้ ({e}) — upsert ทั้งหมด")
            existing = set()
        # ⚠️ race (audit 2026-09-24 MEDIUM): ผู้เรียกส่ง snapshot ที่อ่านไว้ก่อน — writer ที่บันทึกระหว่างนั้น
        # จะไม่อยู่ใน `skills_db` แล้วถูกลบออกจาก index ทั้งที่ไฟล์มี ⇒ ตัดสิน "stale" ด้วย snapshot ∪ **ไฟล์จริง
        # ที่ reload ใต้ `_db_transaction`** (ถือ lock แค่ช่วงลบ = ms) · ห้ามเอา upsert เข้า lock: embed ผ่าน Ollama
        # วัด prod 09-26 = 0.56s warm / 6.73s cold > SKILLS_DB_LOCK_TIMEOUT 5s → writer อื่นจะได้ SkillsDbLocked
        # · ลำดับนี้ airtight เพราะ writer save ไฟล์ *ก่อน* upsert เสมอ และที่นี่อ่าน `existing` *ก่อน* reload เสมอ
        from utils.skills import _db_transaction, _load_skills_db
        with _db_transaction():
            fresh = _load_skills_db()
            wanted = {self._skill_id(t) for t in skills_db} | {self._skill_id(t) for t in fresh}
            stale = sorted(existing - wanted)
            if stale:
                try:
                    self.collection.delete(ids=stale)
                    logger.info(f"sync_from_db: ลบ skill ที่ไม่มีใน db แล้ว {len(stale)} รายการ")
                except Exception as e:
                    logger.error(f"sync_from_db: ลบ stale ids ล้มเหลว: {e}")
        changed, done = _upsert_changed(self.collection, self._skill_id, skills_db, current)
        logger.info(f"sync_from_db: ไม่เปลี่ยน {len(skills_db) - changed} · upsert {done}/{changed} รายการ")
    
    def _space(self) -> Optional[str]:
        """space จริงของ collection ที่ต่ออยู่ — **อ่านจาก metadata ไม่ใช่จากเจตนาในโค้ด**
        collection ที่ถูกสร้างไว้ก่อนหน้านี้ยังคง space เดิมของมัน แม้โค้ดจะขอ cosine แล้ว

        คืน `None` = **อ่านไม่ได้** (ไม่มี collection / metadata ว่าง / ขว้าง exception)
        ⚠️ เดิมกรณีนี้คืน `"l2"` = เอา "ไม่รู้" ไปปนกับ "รู้แล้วว่าเป็น l2" ผลคือวันที่
        08-04 08:20:12 ระบบประกาศว่า collection ผิด space แล้วสั่งให้ลบทิ้งสร้างใหม่
        ทั้งที่ตรวจย้อนหลังแล้ว collection **เป็นตัวเดิม id เดียวกันและเป็น cosine อยู่**
        (รูปแบบที่ 4 ของ measuring-instruments-lie: ไม่มีข้อมูล ถูกนับเป็นค่าที่เจาะจง)
        """
        try:
            space = (self.collection.metadata or {}).get("hnsw:space")
        except Exception:
            return None
        return str(space).lower() if space else None

    def _similarity(self, distance: Optional[float]) -> Optional[float]:
        """แปลง distance → similarity 0..1 · คืน `None` เมื่อแปลงไม่ได้

        `1.0 - distance` ใช้ได้เฉพาะ **cosine** (distance 0..2 → similarity 1..-1)
        ถ้า space เป็น l2 ค่าที่ได้ไม่มีความหมาย (l2 เกิน 1 ได้ง่าย → similarity ติดลบ)
        → คืน `None` = "วัดไม่ได้" ให้ปลายทางตัดสินใจ **ห้ามคืน 0.0** เพราะ
        "ไม่รู้" กับ "ไม่เกี่ยว" ต้องแยกกันให้ออก (กติกาเดียวกับ skills_shadow.py)
        """
        if distance is None or self._space() != "cosine":
            return None
        return max(0.0, min(1.0, 1.0 - float(distance)))

    def search(self, query: str, n_results: int = 3, category: Optional[str] = None) -> List[Dict]:
        """
        Search for relevant skills based on query
        
        Args:
            query: Search query
            n_results: Number of results to return
            category: Filter by category (optional)
        
        Returns:
            List of relevant skills with metadata
        """
        if not self.available or not self.collection:
            logger.warning("Skills search not available, returning empty results")
            return []
        
        try:
            # Build filter if category is specified
            where_filter = None
            if category:
                where_filter = {"category": category}
            
            # Search
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter
            )
            
            # Format results
            skills = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    distance = results['distances'][0][i] if 'distances' in results else None
                    skills.append({
                        "topic": results['metadatas'][0][i]['topic'],
                        "summary": doc,
                        "category": results['metadatas'][0][i]['category'],
                        "source": results['metadatas'][0][i]['source'],
                        "distance": distance,
                        "similarity": self._similarity(distance),
                    })
            
            logger.info(f"Skills search for '{query}' returned {len(skills)} results")
            return skills
        except Exception as e:
            logger.error(f"Skills search failed: {e}")
            return []
    
    def get_all_categories(self) -> List[str]:
        """Get all unique skill categories"""
        if not self.available or not self.collection:
            return []
        
        try:
            # Get all documents and extract unique categories
            results = self.collection.get()
            categories = set()
            for metadata in results.get('metadatas', []):
                if 'category' in metadata:
                    categories.add(metadata['category'])
            return list(categories)
        except Exception as e:
            logger.error(f"Failed to get categories: {e}")
            return []


# Global instance
_skills_search = None
_search_lock = threading.Lock()


def get_skills_search() -> SkillsSearch:
    """Get or create global SkillsSearch instance

    ⚠️ **ต้องถือ lock** — ตั้งแต่ PR #23 เส้นที่เรียกตัวนี้อยู่ใน threadpool (40 slot)
    วัดบน prod: ยิง 12 เธรดพร้อมกันได้ `SkillsSearch` **12 ตัว** แต่ละตัวเปิด
    ChromaDB client + embedding function ของตัวเอง

    ⚠️ **instance ที่ `available=False` ห้าม cache** — เดิมถ้า ChromaDB สะดุดตอน init
    แค่ครั้งเดียว instance ที่มี `collection=None` จะค้างอยู่ตลอดอายุโปรเซส แปลว่า
    `_space()` คืน "อ่านไม่ได้" ตลอดกาล = ฉีด skill ไม่ได้อีกเลยจนกว่าจะ restart แอป
    (และเดิมยังไปรายงานว่าเป็นความผิดของ collection ด้วย)
    """
    global _skills_search
    if _skills_search is not None and _skills_search.available:
        return _skills_search
    with _search_lock:
        # เช็คซ้ำใน lock — เธรดอื่นอาจสร้างเสร็จไปแล้วระหว่างที่เรารอ
        if _skills_search is None or not _skills_search.available:
            _skills_search = SkillsSearch()
        return _skills_search


def recreate_collection() -> str:
    """ลบ `skills_collection` แล้วสร้างใหม่ด้วย cosine space + resync จาก skills_db

    จำเป็นเพราะ **space ของ collection เปลี่ยนตามโค้ดไม่ได้** — collection ที่ถูกสร้าง
    ไว้ตอนโค้ดยังเรียก `client.create_collection()` ตรงๆ จะค้างอยู่บน l2 ตลอดไป
    ต่อให้แก้โค้ดแล้วก็ตาม (แก้โค้ด = collection ที่สร้าง*ใหม่*เท่านั้นที่ได้ cosine)

    รันในคอนเทนเนอร์:
        docker exec ai-backend-1 sh -c "cd /app && python -c \\
          'from utils.skills_search import recreate_collection; print(recreate_collection())'"
    """
    global _skills_search
    from utils.skills import _load_skills_db

    search = get_skills_search()
    if not search.available:
        return "❌ ต่อ ChromaDB ไม่ได้ — ไม่ได้ทำอะไร"

    old_space = search._space() or "อ่านไม่ได้"
    old_count = search.collection.count()
    search.client.delete_collection(search.collection_name)
    _skills_search = None                       # บังคับให้สร้าง instance + collection ใหม่

    fresh = get_skills_search()
    db = _load_skills_db()
    fresh.sync_from_db(db)
    return (
        f"✅ สร้าง {fresh.collection_name} ใหม่: space {old_space} → {fresh._space()} · "
        f"resync {len(db)} skill (เดิม {old_count} รายการ)"
    )


def sync_skills_to_search(skills_db: Dict):
    """
    Sync skills from skills_db.json to ChromaDB search index
    This should be called when skills are updated
    """
    search = get_skills_search()
    if search.available:
        search.sync_from_db(skills_db)     # upsert + ลบของที่หายไปจาก db
        logger.info(f"Synced {len(skills_db)} skills to search index")
