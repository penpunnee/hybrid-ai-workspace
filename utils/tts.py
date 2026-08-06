import os, io, wave, re, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")

# ⚠️ ต้องเป็นโมเดลสาย `*-tts` เท่านั้น — ไฟล์นี้เรียกผ่าน `generate_content()`
# สาย `native-audio` รองรับแค่ `bidiGenerateContent` (Live API, ดู utils/voice.py)
# ยัดเข้ามาที่นี่เมื่อไหร่ = 404 ทุก request เมื่อนั้น (เป็นแบบนั้นอยู่จนถึง 2026-08-06)
# วัดจริงบน prod (ไบต์ PCM 2 รอบ): 2.5-flash-preview-tts → 159886/150286
#                                  3.1-flash-tts-preview → 180480/176640
# เลือก 2.5-flash-preview-tts ให้อยู่ตระกูลเดียวกับ GEMINI_MODEL=gemini-2.5-flash ที่ deploy อยู่
# `tests/test_tts_model.py` ตรึงกติกานี้ไว้แล้ว
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")

# ⚠️ โควตา free tier = **10 request/วัน/โมเดล** ⇒ 1 chunk = 1 request คือของหายาก
# เดิมยิง 1 request ต่อ 1 ประโยค (คำตอบ 5 ประโยค = 5 req) ⇒ ใช้ได้จริง ~2 คำตอบ/วัน
# ตอนนี้จัดกลุ่มประโยคให้เต็ม TTS_MAX_CHARS ก่อน แล้วจำกัดที่ TTS_MAX_CHUNKS
# TTS_MAX_CHARS ต้องไม่เกินขนาดที่ `_generate_one` ส่งได้จริง (มันตัด `text[:TTS_MAX_CHARS]`)
def _positive_env(name: str, default: int) -> int:
    """อ่าน env ที่ต้องเป็นจำนวนเต็มบวก — ค่าเพี้ยนให้ถอยไปใช้ default **พร้อมเตือน**

    เลือกถอยแทน raise เพราะ NAS มี `backend-watchdog` คอย `compose up -d` ทุก 60 วิ
    ⇒ โยน error ตอน import = **crashloop ทั้งระบบเพราะปุ่มลำโพงตัวเดียว**
    แต่ห้ามถอยเงียบ ไม่งั้นคนตั้ง env ไว้จะไม่มีทางรู้ว่ามันไม่มีผล
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        val = int(raw)
        if val <= 0:
            raise ValueError("ต้องเป็นจำนวนเต็มบวก")
        return val
    except ValueError as e:
        logger.warning("%s=%r ใช้ไม่ได้ (%s) — ถอยไปใช้ค่า default %d", name, raw, e, default)
        return default


TTS_MAX_CHARS = _positive_env("TTS_MAX_CHARS", 2000)
TTS_MAX_CHUNKS = _positive_env("TTS_MAX_CHUNKS", 3)

# ⚠️ ตารางเสียงอยู่ที่ `utils/voice.py` ที่เดียว — ห้ามนิยามซ้ำที่นี่อีก
# (เคยมี 2 ก๊อป และตัวที่ `server.py` ใช้จริงคือของไฟล์นี้ ทำให้คนที่ไปแก้ `voice.py`
#  แก้แล้วไม่มีอะไรเกิดขึ้น — `tests/test_voice_consistency.py` กันไว้แล้ว)
from utils.voice import DEFAULT_VOICE, VOICE_MAP, resolve_voice  # noqa: F401


def _pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    """แปลง raw PCM → WAV bytes"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _split_sentences(text: str) -> list[str]:
    """ตัดข้อความเป็น sentences — จบที่ .!?… หรือขึ้นบรรทัดใหม่"""
    parts = re.split(r"(?<=[.!?…])\s+|(?<=\n)", text)
    return [p.strip() for p in parts if p.strip()]


def _pack_sentences(sentences: list[str], max_chars: int) -> list[str]:
    """รวมประโยคต่อกันแบบ greedy จนใกล้ ``max_chars`` แล้วขึ้น chunk ใหม่

    ประโยคเดี่ยวที่ยาวเกิน ``max_chars`` เอง (เช่น bullet list ที่ไม่มีเว้นวรรค
    หรือข้อความที่ `_split_sentences` จับไม่ได้) จะถูก **หั่นแข็ง** เป็นท่อนละ
    ``max_chars`` — ไม่ปล่อยให้ `_generate_one` ตัดทิ้งเงียบๆ
    """
    # ⚠️ กันที่ตัวฟังก์ชันเองด้วย ไม่ใช่แค่ตอนอ่าน env — max_chars <= 0 ทำให้ลูป
    # หั่นแข็งข้างล่างวนไม่รู้จบ (`s[:0]` ว่าง แล้ว `s[0:]` เท่าเดิม) · **hang แย่กว่า crash**
    # เพราะ worker ตายเงียบทีละตัวโดยไม่มี traceback ให้ตาม
    if max_chars <= 0:
        raise ValueError(f"max_chars ต้องเป็นจำนวนเต็มบวก (ได้ {max_chars})")

    chunks: list[str] = []
    buf = ""
    for s in sentences:
        while len(s) > max_chars:  # ประโยคเดี่ยวยาวเกินเพดาน — หั่นแข็ง
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(s[:max_chars])
            s = s[max_chars:]
        if not s:
            continue
        candidate = f"{buf} {s}".strip() if buf else s
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            buf = s
    if buf:
        chunks.append(buf)
    return chunks


def _apply_chunk_cap(chunks: list[str], max_chunks: int) -> list[str]:
    """จำกัดจำนวน chunk ไม่ให้เกิน ``max_chunks`` — **1 chunk = 1 request จากโควตา 10/วัน**

    TODO(pawin): เขียนตรงนี้ — เป็นการชั่งน้ำหนัก "โควตา vs ความครบถ้วนของเสียง"
    ที่ผมตัดสินใจแทนไม่ได้ เพราะขึ้นกับว่าคุณใช้ TTS กับคำตอบแบบไหนจริงๆ

    รับ ``chunks`` ที่ `_pack_sentences` จัดมาแล้ว (แต่ละตัว ≤ TTS_MAX_CHARS)
    คืน list ที่ยาวไม่เกิน ``max_chunks``

    ทางเลือก (เลือกอันเดียวหรือผสมก็ได้):

    1. **ตัดทิ้ง** ``return chunks[:max_chunks]``
       — โควตาแน่นอน · คำตอบยาวมากจะถูกอ่านแค่ต้น (ยาว >6000 ตัวอักษรถึงจะโดน)
    2. **ปล่อยเกินเพดาน** ``return chunks``
       — เสียงครบเสมอ · คำตอบยาวมากกินโควตาเกินคาด (แต่ `_pack_sentences`
         ก็ลดจำนวนลงมากแล้วเทียบของเดิม)
    3. **ยัดท้ายรวมกัน** — เอา chunk ที่เกินมาต่อท้ายตัวสุดท้าย
       ⚠️ **ระวัง**: chunk สุดท้ายจะยาวเกิน ``TTS_MAX_CHARS`` แล้วโดน
       `_generate_one` ตัดทิ้งเงียบๆ = ได้ผลเหมือนข้อ 1 แต่มองไม่เห็น (ไม่แนะนำ)
    4. **โยน error** ให้ผู้ใช้รู้ตัวว่าข้อความยาวเกินจะอ่านได้ในโควตา

    เทสที่ตรึงข้อนี้: ``tests/test_tts_quota.py::test_จำนวน_chunk_ไม่เกินเพดานโควตา``
    (ถ้าเลือกข้อ 2 ต้องแก้เทสตัวนั้นให้ตรงกับเจตนาใหม่ด้วย)
    """
    if len(chunks) <= max_chunks:
        return chunks
    dropped = sum(len(c) for c in chunks[max_chunks:])
    # ตัดทิ้งได้ แต่ **ห้ามหายเงียบ** — ที่ผ่านมาบั๊ก TTS ที่แพงที่สุดคือบั๊กที่ไม่ส่งเสียง
    # (`text[:2000]` ตัดทิ้งมาเป็นเดือนโดยไม่มีใครรู้) จึงต้องมีร่องรอยใน log เสมอ
    logger.warning(
        "TTS ตัดข้อความทิ้ง %d ตัวอักษร — ต้องใช้ %d chunk แต่เพดานอยู่ที่ %d "
        "(ปรับได้ที่ env TTS_MAX_CHUNKS)",
        dropped, len(chunks), max_chunks,
    )
    return chunks[:max_chunks]


def _group_sentences(
    sentences: list[str],
    max_chars: int | None = None,
    max_chunks: int | None = None,
) -> list[str]:
    """จัดกลุ่มประโยค → chunk ที่พร้อมยิงเป็น request (1 chunk = 1 request)"""
    max_chars = TTS_MAX_CHARS if max_chars is None else max_chars
    max_chunks = TTS_MAX_CHUNKS if max_chunks is None else max_chunks
    return _apply_chunk_cap(_pack_sentences(sentences, max_chars), max_chunks)


def _concat_wavs(wavs: list[bytes]) -> bytes:
    """รวม WAV หลายไฟล์เป็นไฟล์เดียว — อ่าน PCM จากทุกไฟล์แล้วต่อกัน"""
    all_pcm = b""
    rate, channels, width = 24000, 1, 2
    for wav_bytes in wavs:
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            all_pcm += wf.readframes(wf.getnframes())
    return _pcm_to_wav(all_pcm, rate, channels, width)


def _generate_one(text: str, voice: str) -> bytes:
    """Generate audio สำหรับ 1 chunk — ใช้ใน ThreadPoolExecutor

    ⚠️ ต้องมี prefix ``Say:`` เสมอ — ส่งข้อความดิบสั้นๆ โมเดลจะเข้าใจว่าเป็น *คำถาม*
    แล้วตอบกลับด้วย 400 ``Model tried to generate text, but it should only be used for TTS``
    (วัดจริง: "สวัสดีค่ะ" ดิบ → 400 · ``Say: สวัสดีค่ะ`` → 48,526 ไบต์ ≈ 1.01 วิ)
    prefix ไม่ถูกอ่านออกเสียง — ประโยคยาวใส่ prefix ได้ 3.53 วิ อยู่ในช่วงเดียวกับแบบดิบ
    (3.13–3.69 วิ จาก 4 ครั้ง) ดูตารางวัดใน ``tests/test_tts_model.py``
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_TTS_MODEL,
        contents=f"Say: {text[:TTS_MAX_CHARS]}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    # โมเดลอาจคืน candidate ที่ content เป็น None (เจอตอน probe) หรือคืนเสียง 0 ไบต์
    # โดยไม่ error เลย (สาย native-audio เคยเป็น) — ทั้งสองเคสต้องดัง ไม่ใช่ส่ง WAV เปล่าออกไป
    cand = response.candidates[0]
    parts = getattr(cand.content, "parts", None) if cand.content else None
    pcm: bytes = parts[0].inline_data.data if parts else b""
    if not pcm:
        raise RuntimeError(
            f"TTS ไม่มีเสียงกลับมา (finish_reason={getattr(cand, 'finish_reason', '?')}, "
            f"model={GEMINI_TTS_MODEL})"
        )
    return _pcm_to_wav(pcm)


def generate_tts(text: str, assistant_slug: str = "") -> bytes:
    """TTS แบบจัดกลุ่มประโยค — **ประหยัดโควตาก่อน แล้วค่อย parallel เท่าที่เหลือ**

    free tier ให้ 10 request/วัน/โมเดล ⇒ จำนวน request คือทรัพยากรที่หายาก ไม่ใช่เวลา
    จึงรวมประโยคให้เต็ม ``TTS_MAX_CHARS`` ก่อน (คำตอบสั้น-กลาง = 1 request)
    แล้ว chunk ที่เหลือค่อยยิงพร้อมกัน (max 4 workers) เพื่อไม่ให้ latency แย่เกินไป

    ⚠️ อย่ากลับไปแบ่งเป็นประโยคย่อยเพื่อลด latency — ``tests/test_tts_quota.py``
    ตรึงไว้แล้วว่าคำตอบ 5 ประโยคต้องยิง 1 request
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set — ไม่สามารถใช้ TTS ได้")

    text = text.strip()
    if not text:
        raise ValueError("text ว่างเปล่า")

    voice = resolve_voice(assistant_slug)
    chunks = _group_sentences(_split_sentences(text))

    # chunk เดียว: ยิงตรงๆ ไม่ต้องเสียค่า thread pool
    if len(chunks) <= 1:
        return _generate_one(chunks[0] if chunks else text[:TTS_MAX_CHARS], voice)

    # หลาย chunk: generate parallel (max 4 workers)
    results: dict[int, bytes] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_generate_one, c, voice): i for i, c in enumerate(chunks)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    ordered = [results[i] for i in range(len(chunks))]
    return _concat_wavs(ordered)
