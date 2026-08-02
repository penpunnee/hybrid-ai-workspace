"""Tests: tool ที่รันไม่ได้ในสภาพแวดล้อมนี้ ต้องไม่โผล่ใน TOOL_REGISTRY (backlog ข้อ 6)

หลักฐานจาก prod 2026-08-03 (ยิง tool ครบ 22 ตัวเป็นครั้งแรก):
`run_python` คืน `❌ exit_code=-1 (blocked) — Docker not available และ
CODE_SANDBOX_ALLOW_LOCAL=false` **ทุกครั้ง** เพราะ container ไม่มี `/var/run/docker.sock`
→ tool นี้ไม่เคยทำงานได้เลยบน prod แต่ยังถูกโฆษณาให้โมเดลเรียก

ทำไมต้องซ่อนแทนที่จะปล่อยให้ error: โมเดลเห็น tool ในทะเบียน → เลือกใช้ → ได้ error →
เสียเทิร์น และบางครั้งพยายามซ้ำ · ทะเบียน tool คือ "สัญญาว่าทำได้" ไม่ใช่รายการความหวัง

⚠️ **ไม่ลบโค้ดทิ้ง** — gate ตามความสามารถจริง เครื่อง dev ที่มี Docker ยังใช้ได้ปกติ
และถ้าวันหน้า mount docker.sock (หรือตั้ง CODE_SANDBOX_ALLOW_LOCAL=true) tool จะกลับมาเอง
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import agents.tools as tools_mod


class TestSandboxCapabilityGate:
    def test_run_python_hidden_when_sandbox_unavailable(self, monkeypatch):
        monkeypatch.setattr(tools_mod, "_sandbox_available", lambda: False)
        assert "run_python" not in tools_mod.build_registry()

    def test_run_python_present_when_sandbox_available(self, monkeypatch):
        monkeypatch.setattr(tools_mod, "_sandbox_available", lambda: True)
        assert "run_python" in tools_mod.build_registry()

    def test_gate_only_removes_that_one_tool(self, monkeypatch):
        monkeypatch.setattr(tools_mod, "_sandbox_available", lambda: True)
        full = set(tools_mod.build_registry())
        monkeypatch.setattr(tools_mod, "_sandbox_available", lambda: False)
        gated = set(tools_mod.build_registry())
        assert full - gated == {"run_python"}, "gate ต้องไม่กระทบ tool อื่น"

    def test_registry_shape_unchanged(self, monkeypatch):
        """ทุก entry ต้องยังมี description/parameters/fn ครบ — ของที่ orchestrator พึ่ง"""
        monkeypatch.setattr(tools_mod, "_sandbox_available", lambda: True)
        for name, spec in tools_mod.build_registry().items():
            assert set(spec) >= {"description", "parameters", "fn"}, name
            assert callable(spec["fn"]), name

    def test_executing_hidden_tool_says_unavailable_not_crash(self, monkeypatch):
        """ถ้ามีคนเรียกชื่อที่ถูก gate ออก ต้องได้ข้อความบอกเหตุ ไม่ใช่ KeyError"""
        monkeypatch.setattr(tools_mod, "_sandbox_available", lambda: False)
        monkeypatch.setattr(tools_mod, "TOOL_REGISTRY", tools_mod.build_registry())
        out = tools_mod.execute_tool("run_python", {"code": "print(1)"})
        assert "run_python" in out or "ไม่" in out
        assert isinstance(out, str)


class TestSandboxAvailable:
    def test_false_when_no_docker_and_local_disabled(self, monkeypatch):
        monkeypatch.setattr("utils.code_sandbox._has_docker", lambda: False)
        monkeypatch.setattr("utils.code_sandbox._ALLOW_LOCAL", False)
        assert tools_mod._sandbox_available() is False

    def test_true_when_docker_present(self, monkeypatch):
        monkeypatch.setattr("utils.code_sandbox._has_docker", lambda: True)
        monkeypatch.setattr("utils.code_sandbox._ALLOW_LOCAL", False)
        assert tools_mod._sandbox_available() is True

    def test_true_when_local_explicitly_allowed(self, monkeypatch):
        monkeypatch.setattr("utils.code_sandbox._has_docker", lambda: False)
        monkeypatch.setattr("utils.code_sandbox._ALLOW_LOCAL", True)
        assert tools_mod._sandbox_available() is True
