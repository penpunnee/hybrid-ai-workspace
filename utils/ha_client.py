"""Home Assistant REST API client

Environment variables:
  HA_URL   — HA base URL เช่น https://ha.pawinhome.com
  HA_TOKEN — Long-Lived Access Token (HA → Profile → Security)
"""
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

HA_URL = os.getenv("HA_URL", "").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_TIMEOUT = int(os.getenv("HA_TIMEOUT", "10"))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def _check_config() -> str | None:
    """คืน error string ถ้า config ไม่ครบ"""
    if not HA_URL:
        return "HA_URL ไม่ได้ตั้งค่าใน .env"
    if not HA_TOKEN:
        return "HA_TOKEN ไม่ได้ตั้งค่าใน .env"
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def search_entities(query: str, max_results: int = 10) -> list[dict]:
    """ค้นหา entity จาก friendly_name หรือ entity_id (case-insensitive substring)

    Returns list of {"entity_id", "friendly_name", "state", "domain"}
    """
    err = _check_config()
    if err:
        return [{"error": err}]

    try:
        resp = requests.get(f"{HA_URL}/api/states", headers=_headers(), timeout=HA_TIMEOUT)
        resp.raise_for_status()
        states: list[dict] = resp.json()
    except Exception as e:
        logger.error(f"[HA] search_entities failed: {e}")
        return [{"error": f"ต่อ HA ไม่ได้: {e}"}]

    q = query.lower()
    matches = []
    for s in states:
        entity_id: str = s.get("entity_id", "")
        friendly: str = s.get("attributes", {}).get("friendly_name", "")
        if q in entity_id.lower() or q in friendly.lower():
            matches.append({
                "entity_id": entity_id,
                "friendly_name": friendly or entity_id,
                "state": s.get("state", "unknown"),
                "domain": entity_id.split(".")[0],
            })
        if len(matches) >= max_results:
            break

    return matches


def get_state(entity_id: str) -> dict:
    """ดึง state + attributes ของ entity

    Returns {"entity_id", "state", "attributes", "last_changed"} หรือ {"error": ...}
    """
    err = _check_config()
    if err:
        return {"error": err}

    try:
        resp = requests.get(
            f"{HA_URL}/api/states/{entity_id}",
            headers=_headers(),
            timeout=HA_TIMEOUT,
        )
        if resp.status_code == 404:
            return {"error": f"ไม่พบ entity: {entity_id}"}
        resp.raise_for_status()
        data = resp.json()
        return {
            "entity_id": data.get("entity_id"),
            "state": data.get("state"),
            "attributes": data.get("attributes", {}),
            "last_changed": data.get("last_changed"),
        }
    except Exception as e:
        logger.error(f"[HA] get_state({entity_id}) failed: {e}")
        return {"error": f"ต่อ HA ไม่ได้: {e}"}


def call_service(
    domain: str,
    service: str,
    entity_id: str = "",
    data: dict | None = None,
) -> dict:
    """เรียก HA service เช่น light.turn_on, climate.set_temperature

    Args:
        domain:    เช่น "light", "switch", "climate", "automation"
        service:   เช่น "turn_on", "turn_off", "set_temperature"
        entity_id: เช่น "light.living_room" (ปล่อยว่างถ้า service ไม่ต้อง)
        data:      extra payload เช่น {"temperature": 25, "hvac_mode": "cool"}

    Returns {"ok": True} หรือ {"error": ...}
    """
    err = _check_config()
    if err:
        return {"error": err}

    payload: dict[str, Any] = dict(data or {})
    if entity_id:
        payload["entity_id"] = entity_id

    try:
        resp = requests.post(
            f"{HA_URL}/api/services/{domain}/{service}",
            headers=_headers(),
            json=payload,
            timeout=HA_TIMEOUT,
        )
        resp.raise_for_status()
        return {"ok": True, "result": resp.json() if resp.content else []}
    except Exception as e:
        logger.error(f"[HA] call_service({domain}.{service}) failed: {e}")
        return {"error": f"ต่อ HA ไม่ได้: {e}"}
