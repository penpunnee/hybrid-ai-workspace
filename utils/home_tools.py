"""
Home Network Tools — NAS Synology API + Wake-on-LAN + Ping
"""
import os, socket, subprocess, logging, json
import urllib.request, urllib.parse

logger = logging.getLogger(__name__)

NAS_IP   = os.getenv("NAS_IP",   "192.168.51.49")
NAS_PORT = int(os.getenv("NAS_PORT", "5000"))
NAS_USER = os.getenv("NAS_USER", "")
NAS_PASS = os.getenv("NAS_PASS", "")
PC_IP    = os.getenv("PC_IP",    "192.168.51.235")
PC_MAC   = os.getenv("PC_MAC",   "")   # xx:xx:xx:xx:xx:xx


# ── Synology DSM Session ──────────────────────────────────────────────────────

def _nas_login() -> str | None:
    try:
        params = urllib.parse.urlencode({
            "api": "SYNO.API.Auth", "version": "3", "method": "login",
            "account": NAS_USER, "passwd": NAS_PASS,
            "session": "HybridAI", "format": "sid",
        })
        resp = urllib.request.urlopen(
            f"http://{NAS_IP}:{NAS_PORT}/webapi/auth.cgi?{params}", timeout=8
        )
        data = json.loads(resp.read())
        if data.get("success"):
            return data["data"]["sid"]
    except Exception as e:
        logger.error(f"NAS login error: {e}")
    return None


def _nas_logout(sid: str):
    try:
        params = urllib.parse.urlencode({
            "api": "SYNO.API.Auth", "version": "1", "method": "logout",
            "session": "HybridAI", "_sid": sid,
        })
        urllib.request.urlopen(
            f"http://{NAS_IP}:{NAS_PORT}/webapi/auth.cgi?{params}", timeout=5
        )
    except Exception:
        pass


def _nas_api(api: str, version: int, method: str, sid: str, extra: dict = {}) -> dict:
    params = urllib.parse.urlencode({
        "api": api, "version": version, "method": method, "_sid": sid, **extra
    })
    resp = urllib.request.urlopen(
        f"http://{NAS_IP}:{NAS_PORT}/webapi/entry.cgi?{params}", timeout=12
    )
    return json.loads(resp.read())


# ── NAS Tools ────────────────────────────────────────────────────────────────

def nas_disk_usage() -> dict:
    if not NAS_USER or not NAS_PASS:
        return {"error": "ยังไม่ตั้งค่า NAS_USER / NAS_PASS ใน .env"}
    sid = _nas_login()
    if not sid:
        return {"error": f"Login NAS {NAS_IP} ไม่สำเร็จ — ตรวจสอบ NAS_USER / NAS_PASS"}
    try:
        # ลอง DSM 7 API ก่อน แล้ว fallback ไป DSM 6
        data = _nas_api("SYNO.Core.Storage.Volume", 1, "list", sid, {"limit": -1})
        raw_volumes = data.get("data", {}).get("volumes", []) if data.get("success") else []

        # DSM 7 อาจใช้ SYNO.Storage.CGI.Storage
        if not raw_volumes:
            data2 = _nas_api("SYNO.Storage.CGI.Storage", 1, "load_info", sid)
            if data2.get("success"):
                raw_volumes = data2.get("data", {}).get("volumes", [])

        volumes = []
        for v in raw_volumes:
            # DSM 7 format
            size_info = v.get("size", {})
            total = size_info.get("total", 0) or v.get("total_size", 0)
            used  = size_info.get("used",  0) or v.get("used_size",  0)
            free  = total - used
            if total == 0:
                continue
            volumes.append({
                "path":     v.get("vol_path", v.get("id", "volume")),
                "total_gb": round(total / 1e9, 1),
                "used_gb":  round(used  / 1e9, 1),
                "free_gb":  round(free  / 1e9, 1),
                "percent":  round(used / total * 100, 1),
                "status":   v.get("status", "normal"),
            })

        # ถ้ายังว่างอยู่ ดึงจาก /api/v2 ตรงๆ
        if not volumes:
            try:
                resp = urllib.request.urlopen(
                    f"http://{NAS_IP}:{NAS_PORT}/webapi/entry.cgi?"
                    f"api=SYNO.Core.Storage.Volume&version=1&method=list&limit=-1&_sid={sid}",
                    timeout=12
                )
                raw = json.loads(resp.read())
                logger.debug(f"NAS disk raw response: {str(raw)[:500]}")
                return {"ok": True, "volumes": [], "nas_ip": NAS_IP, "raw": raw}
            except Exception:
                pass

        return {"ok": True, "volumes": volumes, "nas_ip": NAS_IP}
    except Exception as e:
        logger.error(f"nas_disk_usage error: {e}")
        return {"error": str(e)}
    finally:
        _nas_logout(sid)


def nas_docker_status() -> dict:
    if not NAS_USER or not NAS_PASS:
        return {"error": "ยังไม่ตั้งค่า NAS_USER / NAS_PASS ใน .env"}
    sid = _nas_login()
    if not sid:
        return {"error": f"Login NAS {NAS_IP} ไม่สำเร็จ"}
    try:
        data = _nas_api("SYNO.Docker.Container", 1, "list", sid, {"limit": 50})
        containers = []
        if data.get("success"):
            for c in data["data"].get("containers", []):
                containers.append({
                    "name":    c.get("name", ""),
                    "status":  c.get("status", ""),
                    "running": c.get("status", "") == "running",
                    "image":   c.get("image", ""),
                })
        return {"ok": True, "containers": containers, "nas_ip": NAS_IP}
    except Exception as e:
        logger.error(f"nas_docker_status error: {e}")
        return {"error": str(e)}
    finally:
        _nas_logout(sid)


def nas_system_info() -> dict:
    if not NAS_USER or not NAS_PASS:
        return {"error": "ยังไม่ตั้งค่า NAS_USER / NAS_PASS ใน .env"}
    sid = _nas_login()
    if not sid:
        return {"error": f"Login NAS {NAS_IP} ไม่สำเร็จ"}
    try:
        info  = _nas_api("SYNO.Core.System", 1, "info", sid)
        uinfo = _nas_api("SYNO.Core.System.Utilization", 1, "get", sid)
        result: dict = {"ok": True, "nas_ip": NAS_IP}
        if info.get("success"):
            d = info["data"]
            result["model"]       = d.get("model", "")
            result["serial"]      = d.get("serial", "")
            result["ram_mb"]      = d.get("ram_size", 0)
            result["dsm_version"] = d.get("firmware_ver", "")
            result["uptime_days"] = round(d.get("up_time", 0) / 86400, 1)
        if uinfo.get("success"):
            u = uinfo["data"]
            result["cpu_percent"] = u.get("cpu", {}).get("user_load", 0)
            result["ram_used_percent"] = round(
                u.get("memory", {}).get("real_usage", 0) / 100, 1
            ) if "memory" in u else None
        return result
    except Exception as e:
        logger.error(f"nas_system_info error: {e}")
        return {"error": str(e)}
    finally:
        _nas_logout(sid)


def home_status_all() -> dict:
    """รวม disk + docker + ping PC ในครั้งเดียว"""
    disk   = nas_disk_usage()
    docker = nas_docker_status()
    pc     = ping_device(PC_IP)
    return {"disk": disk, "docker": docker, "pc": pc}


# ── Wake-on-LAN ───────────────────────────────────────────────────────────────

def wol_pc() -> dict:
    if not PC_MAC:
        return {
            "error": (
                "ยังไม่ตั้งค่า PC_MAC ใน .env\n"
                "ดู MAC ด้วย: ipconfig /all (Windows) หรือ ip link show (Linux)\n"
                f"แล้วเพิ่ม: PC_MAC=xx:xx:xx:xx:xx:xx"
            )
        }
    try:
        mac = PC_MAC.replace(":", "").replace("-", "")
        if len(mac) != 12:
            return {"error": f"PC_MAC ไม่ถูกต้อง: {PC_MAC}"}
        mac_bytes = bytes.fromhex(mac)
        magic = b"\xff" * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(magic, ("<broadcast>", 9))
        logger.info(f"WoL sent to {PC_MAC} ({PC_IP})")
        return {"ok": True, "mac": PC_MAC, "ip": PC_IP,
                "message": f"ส่ง Wake-on-LAN ไปยัง {PC_MAC} แล้ว — PC ควรเปิดใน ~30 วินาที"}
    except Exception as e:
        logger.error(f"WoL error: {e}")
        return {"error": str(e)}


# ── Ping ──────────────────────────────────────────────────────────────────────

def ping_device(ip: str) -> dict:
    try:
        result = subprocess.run(
            ["ping", "-c", "3", "-W", "2", ip],
            capture_output=True, text=True, timeout=12
        )
        online = result.returncode == 0
        latency = None
        for line in result.stdout.splitlines():
            if "min/avg/max" in line or "rtt" in line:
                parts = line.split("=")[-1].strip().split("/")
                if len(parts) >= 2:
                    try:
                        latency = float(parts[1])
                    except ValueError:
                        pass
        return {"ip": ip, "online": online, "latency_ms": latency}
    except subprocess.TimeoutExpired:
        return {"ip": ip, "online": False, "latency_ms": None}
    except Exception as e:
        return {"ip": ip, "online": False, "error": str(e)}


# ── Keyword Detection ─────────────────────────────────────────────────────────

_DISK_KW    = {"disk", "storage", "พื้นที่", "ดิสก์", "เนื้อที่", "เต็ม", "ว่าง", "เหลือ"}
_DOCKER_KW  = {"docker", "container", "คอนเทนเนอร์", "service", "รัน", "หยุด"}
_WOL_KW     = {"เปิด pc", "เปิดpc", "wake", "wol", "ปลุก", "เปิดคอม"}
_PING_KW    = {"ping", "ออนไลน์", "online", "pc ออน", "pc เปิด", "pcเปิด", "pc อยู่ไหม"}
_NAS_KW     = {"nas", "synology", "เนส", "เซิร์ฟเวอร์บ้าน"}


def detect_home_tools(prompt: str) -> list[str]:
    """คืน list ของ tools ที่ควรเรียกตาม prompt"""
    p = prompt.lower()
    tools = []
    if any(kw in p for kw in _DISK_KW | _NAS_KW):
        tools.append("disk")
    if any(kw in p for kw in _DOCKER_KW):
        tools.append("docker")
    if any(kw in p for kw in _WOL_KW):
        tools.append("wol")
    if any(kw in p for kw in _PING_KW):
        tools.append("ping_pc")
    return tools


def build_tool_context(tools: list[str]) -> str:
    """เรียก tools และสร้าง context string ให้ AI"""
    parts = []
    for tool in tools:
        if tool == "disk":
            r = nas_disk_usage()
            if r.get("ok"):
                lines = [f"[ข้อมูล NAS Disk — {NAS_IP}]"]
                for v in r.get("volumes", []):
                    lines.append(
                        f"• {v['path']}: ใช้ {v['used_gb']}GB / {v['total_gb']}GB "
                        f"({v['percent']}%) | เหลือ {v['free_gb']}GB | status: {v['status']}"
                    )
                parts.append("\n".join(lines))
            elif r.get("error"):
                parts.append(f"[NAS Disk] Error: {r['error']}")

        elif tool == "docker":
            r = nas_docker_status()
            if r.get("ok"):
                lines = [f"[Docker Containers บน NAS — {NAS_IP}]"]
                for c in r.get("containers", []):
                    icon = "🟢" if c["running"] else "🔴"
                    lines.append(f"• {icon} {c['name']} ({c['status']})")
                parts.append("\n".join(lines))
            elif r.get("error"):
                parts.append(f"[Docker] Error: {r['error']}")

        elif tool == "wol":
            r = wol_pc()
            if r.get("ok"):
                parts.append(f"[Wake-on-LAN] {r['message']}")
            elif r.get("error"):
                parts.append(f"[Wake-on-LAN] Error: {r['error']}")

        elif tool == "ping_pc":
            r = ping_device(PC_IP)
            status = "🟢 Online" if r["online"] else "🔴 Offline"
            lat = f" ({r['latency_ms']:.1f}ms)" if r.get("latency_ms") else ""
            parts.append(f"[PC Status — {PC_IP}] {status}{lat}")

    return "\n\n".join(parts)
