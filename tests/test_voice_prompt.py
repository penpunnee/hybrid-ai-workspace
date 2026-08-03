"""voice ต้องไม่ใช้ persona ของแชทดิบๆ — มันถามกลับกลางเรื่องจนเสียงหยุด

**เคสจริง (user รายงาน 2026-08-04):** ให้โมเดลอ่านนิยาย/เล่ายาวๆ ผ่าน voice แล้ว
"เล่าได้สักช่วง จะมีคำถามกลับมาว่า จะให้เล่าต่อเลยไหมคะ เหมือนจะถามแบบนี้ตลอด
ถ้าเล่าจบช่วงหนึ่ง" → ต้องพูดตอบทุกครั้งถึงจะเล่าต่อ

**ต้นเหตุ:** `server.py` เอา `ASSISTANTS[x]["system_prompt"]` ไปใช้กับ Gemini Live ตรงๆ
persona นั้นเขียนไว้ว่า *"ตรงประเด็น กระชับ ไม่อ้อมค้อม ถ้าเรื่องซับซ้อนให้แบ่งเป็นขั้นตอน"*
และ *"[หน้าที่เลขา] เสนอแนะเชิงรุก ... ให้ถามไถ่"* — ดีสำหรับแชท แต่ใน voice
**การถามกลับ 1 ครั้ง = เสียงหยุดทั้งหมด + บังคับให้คนพูดตอบ** ต้นทุนต่างกันคนละโลก

⚠️ **ข้อจำกัดของเทสชุดนี้:** เทสได้แค่ "ต่อสายถูก" (voice ใช้ prompt คนละตัวกับแชท และ
กติกาอยู่ในนั้นจริง) — **พิสูจน์ไม่ได้ว่าโมเดลจะเชื่อฟัง** พฤติกรรมจริงต้องให้ user ลองเล่า
นิยายอีกรอบแล้วดูว่ายังถามกลับไหม เทสนี้กันแค่ "มีคนไปถอด/เปลี่ยน prompt แล้วไม่มีใครรู้"
"""

from assistants.config import ASSISTANTS, voice_system_prompt


class TestVoicePromptIsSeparate:
    def test_voice_prompt_differs_from_chat_prompt(self):
        for name, asst in ASSISTANTS.items():
            slug = asst.get("slug", "")
            chat = asst.get("system_prompt", "")
            voice = voice_system_prompt(slug)
            assert voice != chat, f"{name}: voice ใช้ prompt เดียวกับแชท — จะถามกลับกลางเรื่อง"
            assert chat in voice, f"{name}: voice ต้องคงบุคลิกเดิมไว้ แล้วต่อกติกาเสียงเพิ่ม"

    def test_voice_prompt_forbids_asking_permission_to_continue(self):
        """กติกาที่ปิดอาการโดยตรง — ห้ามถามขออนุญาตเล่าต่อ"""
        voice = voice_system_prompt("kwan")
        assert "เล่าต่อ" in voice or "ต่อเลย" in voice, "ไม่มีกติกาเรื่องการเล่าต่อเนื่องเลย"
        assert "ห้ามถาม" in voice, "ไม่ได้ห้ามถามขออนุญาตกลางเรื่อง"

    def test_unknown_slug_still_gets_voice_rules(self):
        """slug ที่ไม่รู้จักต้องไม่หลุดไปได้ prompt เปล่าที่ไม่มีกติกาเสียง"""
        voice = voice_system_prompt("ไม่มีผู้ช่วยนี้")
        assert "ห้ามถาม" in voice
        assert voice.strip() != ""


class TestServerUsesIt:
    """กันการถอยกลับไปอ่าน system_prompt ดิบใน handler"""

    def test_server_calls_voice_system_prompt(self):
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "server.py"
        text = src.read_text(encoding="utf-8")
        ws_block = text[text.index('@app.websocket("/ws/voice/'):]
        ws_block = ws_block[: ws_block.index("\n@app.") if "\n@app." in ws_block else len(ws_block)]

        assert "voice_system_prompt(" in ws_block, (
            "voice handler ไม่ได้เรียก voice_system_prompt() → กลับไปใช้ persona แชทดิบๆ "
            "ซึ่งจะถามกลับกลางเรื่องจนเสียงหยุด"
        )
        assert 'asst.get("system_prompt"' not in ws_block, (
            "voice handler ยังอ่าน system_prompt ดิบอยู่"
        )
