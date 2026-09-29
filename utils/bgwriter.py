"""เขียนเบื้องหลังตามลำดับ — ย้ายงาน sync ช้า (sqlite commit) ออกจาก event loop ของ WS โดยไม่สลับลำดับ (2026-09-29)

วัดบน prod (5B `[LoopTiming]`): `_save_msg` ของ /ws/voice 0.8–1.7 วิ/ครั้ง × 2/turn บน event loop · ต้นเหตุ fsync บน
RAID5 HDD 5,400 rpm (dd dsync 213 ms/ครั้ง) → ย้ายเข้า worker ตัวเดียว:
· `ThreadPoolExecutor(max_workers=1)` = คิว FIFO + worker เดียว ⇒ user→assistant เขียนตามลำดับที่ส่งเสมอ
  (`asyncio.to_thread` ใช้ default executor หลาย worker → fire-and-forget ลำดับไม่รับประกัน)
· ผู้เรียกได้ `None` ทันที (voice ไม่ใช้ id ที่ save_message คืน) · exception ใน worker ต้อง log เอง
  (future ที่ไม่มีใครรอ = exception หายเงียบ)
· `close()` = `shutdown(wait=False)` ไม่ยกเลิกงานที่ค้าง (docs concurrent.futures) ⇒ ปิดสายแล้วข้อความไม่หาย ·
  `then` = งานสุดท้ายในคิว (เช่น log สรุปที่ต้องออกหลังบันทึกครบ)
"""
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class OrderedBackgroundWriter:
    def __init__(self, name: str):
        self.name = name
        self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)

    def _log_exc(self, fut) -> None:
        exc = fut.exception()
        if exc is not None:
            logger.error(f"[BgWriter] {self.name} งานล้ม: {type(exc).__name__}: {exc}")

    def wrap(self, fn):
        def submit(*args, **kwargs):
            self._ex.submit(fn, *args, **kwargs).add_done_callback(self._log_exc)
            return None
        return submit

    def close(self, then=None, wait_for_test: bool = False) -> None:
        if then is not None:
            self._ex.submit(then).add_done_callback(self._log_exc)
        self._ex.shutdown(wait=wait_for_test)
