"""ChromaDB ต้องไม่เปิดพอร์ตให้ LAN (ปอยเคาะ 2026-10-07 · devlog [ต่อ 144–145])

ChromaDB ไม่มี auth — ใครต่อพอร์ตได้ก็อ่าน/เขียน/ลบความจำได้ทั้งหมด
และมี CVE ฝั่งเซิร์ฟเวอร์ที่ยังไม่มี fix (docs/reference/security-accepted-risks.md)
⇒ publish ได้เฉพาะ 127.0.0.1 · backend ต่อด้วยชื่อ service `chromadb` ผ่าน docker network
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _chroma_ports():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = compose["services"]["chromadb"]
    return svc.get("ports") or []


def test_chromadb_service_exists():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "chromadb" in compose["services"]


def test_chromadb_ports_bind_loopback_only():
    for p in _chroma_ports():
        if isinstance(p, dict):  # long syntax
            host_ip = p.get("host_ip", "")
        else:
            parts = str(p).split(":")
            # "8000" / "8000:8000" = ทุก interface · "IP:host:container" = ระบุ IP
            host_ip = parts[0] if len(parts) == 3 else ""
        assert host_ip == "127.0.0.1", (
            f"ports {p!r} ของ chromadb เปิดให้ LAN — ต้องเป็น 127.0.0.1:<host>:<container>"
        )
