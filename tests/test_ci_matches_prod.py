"""ตรึงว่า CI ตรวจสิ่งเดียวกับที่ prod รัน (audit backlog ข้อ 22)

ข้อ 22 เขียนไว้ว่าปัญหาคือ "CI ลงจาก requirements.txt แต่ prod ลงจาก requirements.lock"
วัดจริง 2026-08-03 พบว่ากว้างกว่านั้น — CI กับ prod ต่างกัน 3 แกนพร้อมกัน:

  1. เวอร์ชัน package — CI resolve สดจาก requirements.txt vs prod pin จาก requirements.lock
     (drift ~34/121 ตัว รวม cryptography ข้าม major 49 → 50)
  2. Python — CI ตั้ง 3.12 ผ่าน setup-python vs prod 3.11.15
     (ยิง `docker exec ai-backend-1 python -V` เข้าคอนเทนเนอร์จริงยืนยันแล้ว ไม่ได้อ่านจาก Dockerfile)
  3. system deps — image ลง poppler-utils (utils/ocr.py ต้องใช้) แต่ runner ของ CI ไม่มี

ทางแก้ที่เลือก: ให้ CI รัน pytest **ในอิมเมจที่ deploy จริง** (docker-compose `build: .`)
→ ปิดครบทั้ง 3 แกนด้วยแหล่งความจริงเดียวคือ Dockerfile แทนที่จะไปไล่ sync ค่า 3 ที่ใน yml
ให้ตรงกับ Dockerfile เองซึ่งไม่มีอะไรบังคับ

เทสในไฟล์นี้ตรึงข้อตกลงนั้นไว้ ไม่ให้ถอยกลับไปเงียบๆ
"""

import re
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"
CANARY = REPO / ".github" / "workflows" / "canary.yml"
DOCKERFILE = REPO / "Dockerfile"
REQ_TXT = REPO / "requirements.txt"
REQ_LOCK = REPO / "requirements.lock"

def _norm(name: str) -> str:
    """ชื่อแพ็กเกจตาม PEP 503 — `PyYAML`, `pyyaml`, `py_yaml` คือตัวเดียวกัน"""
    return re.sub(r"[-_.]+", "-", name).lower()


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run_lines(steps: list[dict]) -> str:
    """รวมทุกคำสั่งใน `run:` ของทุก step เป็นข้อความก้อนเดียวไว้ค้น"""
    return "\n".join(s.get("run", "") for s in steps if isinstance(s, dict))


def _blocking_pytest_job(workflow: dict) -> tuple[str, list[dict]]:
    """คืน (ชื่อ job, steps) ของ job ที่เป็น "ด่านจริง" ในการรัน pytest

    ไม่ hardcode ชื่อ job — ค้นจากพฤติกรรม (job ไหนรัน pytest) เพื่อให้ทนต่อการเปลี่ยนชื่อ
    แต่ถ้าหาไม่เจอหรือกำกวมจะ **ล้มดังๆ ไม่คืนลิสต์ว่าง**: assertion เชิงลบด้านล่าง
    (`ต้องไม่มี pip install requirements.txt`) เป็นจริงโดยปริยายทันทีที่ชุดที่ตรวจว่างเปล่า
    → "หาไม่เจอ" จะกลายเป็น "ผ่าน" ซึ่งคือ guard ที่ตายเงียบ (พิสูจน์แล้ว 2026-08-03
    ด้วยการแกล้งชี้ไป job ที่ไม่มีจริง แล้วเทสตัวนั้นผ่านฟรี)

    job ที่ตั้ง `continue-on-error: true` ไม่นับเป็นด่าน — เผื่อ canary job ที่ตั้งใจ
    resolve สดจาก requirements.txt เพื่อดัก upstream breakage ล่วงหน้า มันไม่บล็อก merge
    """
    jobs = workflow.get("jobs") or {}
    found: dict[str, list[dict]] = {}
    for name, spec in jobs.items():
        if not isinstance(spec, dict) or spec.get("continue-on-error") is True:
            continue
        steps = spec.get("steps") or []
        if re.search(r"\bpytest\b", _run_lines(steps)):
            found[name] = steps

    wf = WORKFLOW.relative_to(REPO)
    if not found:
        pytest.fail(
            f"หา job ที่รัน pytest ใน {wf} ไม่เจอเลย — เทสด้านล่างจะผ่านฟรีถ้าปล่อยผ่าน "
            f"จุดนี้ ตรวจว่า workflow ถูกเปลี่ยนโครงสร้าง/เปลี่ยนที่อยู่หรือไม่"
        )
    if len(found) > 1:
        pytest.fail(
            f"เจอ job ที่รัน pytest และบล็อก merge มากกว่าหนึ่งใน {wf}: {sorted(found)} "
            f"→ ไม่รู้ว่าอันไหนคือด่านจริง ถ้าตั้งใจมีหลายอัน ให้ตั้ง continue-on-error: true "
            f"กับตัวที่ไม่ใช่ด่าน หรือแก้เทสนี้ให้ตรวจทุกอัน"
        )
    return next(iter(found.items()))


def _lock_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in REQ_LOCK.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        out[_norm(name)] = version.strip()
    return out


def _txt_requirements() -> list[Requirement]:
    out = []
    for line in REQ_TXT.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.append(Requirement(line))
    return out


class TestCIRunsWhatProdRuns:
    """CI ต้องเทสอิมเมจที่ deploy จริง ไม่ใช่สภาพแวดล้อมที่ประกอบขึ้นใหม่ใน runner"""

    def test_pytest_runs_inside_deploy_image(self):
        """pytest ต้องถูกรันในอิมเมจที่ build จาก Dockerfile ของ repo นี้

        นี่คือข้อที่ปิดทั้ง 3 แกนพร้อมกัน — python เวอร์ชันไหน, lib เวอร์ชันไหน,
        มี poppler ไหม ล้วนถูกกำหนดโดย Dockerfile ตัวเดียว
        """
        job, steps = _blocking_pytest_job(_load_workflow())
        runs = _run_lines(steps)

        # รับทั้ง `docker build` และ `docker buildx build` — ตรวจเจตนา ไม่ใช่การสะกด
        assert re.search(r"docker\s+(?:buildx\s+)?build\b", runs), (
            f"job '{job}' ไม่ได้ build อิมเมจเลย → เทสรันบนสภาพแวดล้อมที่ประกอบเองใน runner "
            f"ซึ่งไม่ผูกกับ Dockerfile ที่ prod ใช้"
        )
        assert re.search(r"docker run\b[^\n]*pytest", runs), (
            f"job '{job}' ไม่ได้รัน pytest ผ่าน `docker run` → เทสไม่ได้เทสอิมเมจที่ deploy จริง"
        )

    def test_test_job_does_not_install_from_requirements_txt(self):
        """job ที่รันเทสต้องไม่ pip install จาก requirements.txt

        requirements.txt เป็น spec หลวม (`>=`) ไว้อ่าน/อัปเกรดโดยตั้งใจ — resolve สดจากมัน
        ได้เวอร์ชันที่ prod ไม่เคยรัน (Dockerfile:12-13 ลงจาก requirements.lock เท่านั้น)
        """
        _job, steps = _blocking_pytest_job(_load_workflow())
        runs = _run_lines(steps)

        assert not re.search(r"pip install[^\n]*requirements\.txt", runs), (
            "job รันเทสยัง pip install -r requirements.txt อยู่ → CI จะได้เวอร์ชันคนละชุดกับ prod "
            "(วัด 2026-08-03: ต่างกัน ~34/121 ตัว รวม cryptography ข้าม major)"
        )


class TestCanaryStaysNonBlockingAndLoud:
    """canary ต้องเป็นเส้นตรงข้ามกับ tests.yml — resolve สด, แดงได้, แต่บล็อก merge ไม่ได้

    tests.yml ปิดช่องว่าง CI≠prod ด้วยการลงจาก lock เสมอ ผลข้างเคียงคือ **ไม่มีวันเห็น
    upstream breaking change ล่วงหน้าอีก** (ตัวที่จับ `mcp` 2.0 ได้คือการ resolve สดพอดี)
    canary รับหน้าที่นั้นแทน — เทสชุดนี้กันไม่ให้มันกลายพันธุ์ไปเป็นอย่างอื่น
    """

    def _canary(self) -> dict:
        assert CANARY.exists(), (
            f"ไม่มี {CANARY.relative_to(REPO)} — ถ้าจงใจเลิกใช้ canary ให้ลบเทสคลาสนี้ด้วย "
            f"ไม่งั้นจะเหลือแค่ความเชื่อว่ามีคนเฝ้า upstream อยู่"
        )
        return yaml.safe_load(CANARY.read_text(encoding="utf-8"))

    def test_canary_never_runs_on_pull_request(self):
        """canary ต้องไม่ผูกกับ PR — ไม่งั้นมันบล็อก merge จาก breakage ที่ไม่ใช่ความผิดของ PR นั้น"""
        # `on:` ใน YAML ถูก parse เป็น boolean True (YAML 1.1) — รับทั้งสองคีย์
        triggers = self._canary().get("on") or self._canary().get(True) or {}
        assert "pull_request" not in triggers, (
            "canary ตั้ง trigger `pull_request` → จะบล็อก merge ทั้งที่หน้าที่มันคือเตือนล่วงหน้า "
            "ไม่ใช่เป็นด่าน (upstream พังไม่ใช่ความผิดของ PR ที่กำลังรีวิว)"
        )
        assert "schedule" in triggers, (
            "canary ไม่มี `schedule` → ไม่มีอะไรรันมันเองเลย กลายเป็นสคริปต์ที่ต้องรอคนจำได้"
        )

    def test_canary_failure_is_not_swallowed(self):
        """ห้ามใช้ continue-on-error — มันทำให้ job รายงาน success ทั้งที่ข้างในแดง"""
        for name, spec in (self._canary().get("jobs") or {}).items():
            assert spec.get("continue-on-error") is not True, (
                f"canary job '{name}' ตั้ง continue-on-error: true → GitHub จะรายงานผลเป็น success "
                f"แม้เทสข้างในแดง = เตือนแล้วไม่มีใครเห็น (ไม่ต้องใช้ flag นี้เลย เพราะ canary "
                f"ไม่ได้ผูกกับ pull_request จึงบล็อก merge ไม่ได้อยู่แล้ว)"
            )

    def test_canary_resolves_fresh_from_requirements_txt(self):
        """เหตุผลเดียวที่ canary มีอยู่ — ต้อง resolve สด ไม่ใช่ลงจาก lock ซ้ำกับ tests.yml"""
        runs = "\n".join(
            _run_lines(spec.get("steps") or [])
            for spec in (self._canary().get("jobs") or {}).values()
        )
        assert re.search(r"pip install[^\n]*requirements\.txt", runs), (
            "canary ไม่ได้ลงจาก requirements.txt → มันจะเทสเวอร์ชันชุดเดียวกับ tests.yml "
            "แปลว่าไม่มีอะไรเฝ้า upstream อยู่จริง"
        )
        assert not re.search(r"pip install[^\n]*requirements\.lock", runs), (
            "canary ลงจาก requirements.lock → ซ้ำกับ tests.yml และไม่มีวันเห็นของใหม่จาก upstream"
        )
        assert re.search(r"\bpytest\b", runs), "canary ไม่ได้รัน pytest → ไม่รู้ว่า deps ใหม่ทำอะไรพังหรือเปล่า"


class TestLockHonoursSpec:
    """requirements.lock (ของที่ prod รัน) ต้องทำตามข้อกำหนดใน requirements.txt

    ถ้าไม่ตรึงไว้ สองไฟล์นี้ลอยแยกกันได้อิสระ — pin `mcp>=1.27.0,<2` ที่ใส่ 2026-08-03
    จึงมีผลกับ CI อย่างเดียว ไม่แตะ prod เลย เพราะไม่มีใครเช็คว่า lock ทำตามหรือเปล่า
    """

    def test_every_pinned_requirement_is_in_lock(self):
        lock = _lock_versions()
        missing = [r.name for r in _txt_requirements() if _norm(r.name) not in lock]
        assert not missing, (
            f"แพ็กเกจใน requirements.txt ที่ไม่มีใน requirements.lock: {missing} "
            f"→ prod จะไม่ได้ลงตัวนี้เลย ทั้งที่ spec สั่งไว้"
        )

    def test_lock_versions_satisfy_spec(self):
        lock = _lock_versions()
        violations = []
        for req in _txt_requirements():
            key = _norm(req.name)
            if key not in lock:
                continue  # ถูกจับโดยเทสข้างบนแล้ว
            if Version(lock[key]) not in req.specifier:
                violations.append(f"{req.name}: spec={req.specifier} แต่ lock มี {lock[key]}")
        assert not violations, (
            "requirements.lock ไม่ทำตาม requirements.txt:\n  " + "\n  ".join(violations)
            + "\n→ ข้อจำกัดที่เขียนใน requirements.txt ไม่มีผลกับ prod"
        )
