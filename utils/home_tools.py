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


def _default_gateway(ip: str) -> str:
    """เดา router/gateway จาก subnet (x.y.z.1) — ใช้เมื่อไม่ตั้ง ROUTER_IP"""
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return ".".join(parts[:3] + ["1"])
    return ip


ROUTER_IP = os.getenv("ROUTER_IP", _default_gateway(NAS_IP))


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
            size_info = v.get("size", {})
            total = int(size_info.get("total", 0) or v.get("total_size", 0) or 0)
            used  = int(size_info.get("used",  0) or v.get("used_size",  0) or 0)
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
        containers = []
        # ลอง SYNO.Docker.Container API หลายเวอร์ชัน
        for api, ver, method in [
            ("SYNO.Docker.Container", 1, "list"),
            ("SYNO.Docker.Container", 2, "list"),
            ("SYNO.Docker.Container.Profile", 1, "list"),
        ]:
            try:
                data = _nas_api(api, ver, method, sid, {"limit": 50, "offset": 0})
                if data.get("success") and data.get("data"):
                    raw = data["data"].get("containers", data["data"].get("profiles", []))
                    for c in raw:
                        containers.append({
                            "name":    c.get("name", c.get("id", "")),
                            "status":  c.get("status", c.get("state", "")),
                            "running": c.get("status", c.get("state", "")) in ("running", "up"),
                            "image":   c.get("image", ""),
                        })
                    if containers:
                        break
            except Exception:
                continue

        # fallback: ดึงจาก docker ps ผ่าน SSH subprocess (ถ้า API ไม่ work)
        if not containers:
            try:
                import subprocess
                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
                    capture_output=True, text=True, timeout=8
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().splitlines():
                        parts = line.split("\t")
                        if len(parts) >= 2:
                            containers.append({
                                "name":    parts[0],
                                "status":  parts[1] if len(parts) > 1 else "",
                                "running": True,
                                "image":   parts[2] if len(parts) > 2 else "",
                            })
            except Exception as e:
                logger.debug(f"docker ps fallback failed: {e}")

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
                "แล้วเพิ่ม: PC_MAC=xx:xx:xx:xx:xx:xx"
            )
        }
    try:
        mac = PC_MAC.replace(":", "").replace("-", "")
        if len(mac) != 12:
            return {"error": f"PC_MAC ไม่ถูกต้อง: {PC_MAC}"}
        mac_bytes = bytes.fromhex(mac)
        magic = b"\xff" * 6 + mac_bytes * 16

        # คำนวณ LAN broadcast address จาก PC_IP (ใช้ /24 subnet)
        ip_parts = PC_IP.split(".")
        lan_broadcast = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"

        sent_to = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # ส่งหลาย targets เพื่อให้แน่ใจว่าถึง PC
            for target in [lan_broadcast, "255.255.255.255", PC_IP]:
                for port in [9, 7]:
                    try:
                        s.sendto(magic, (target, port))
                        sent_to.append(f"{target}:{port}")
                    except Exception:
                        pass

        logger.info(f"WoL sent to {PC_MAC} via {sent_to}")
        return {"ok": True, "mac": PC_MAC, "ip": PC_IP,
                "message": f"ส่ง WoL ไปยัง {PC_MAC} ({lan_broadcast}) แล้ว — รอ ~30 วินาที"}
    except Exception as e:
        logger.error(f"WoL error: {e}")
        return {"error": str(e)}


# ── Ping ──────────────────────────────────────────────────────────────────────

def ping_device(ip: str) -> dict:
    """ตรวจสอบ device online ด้วย TCP port check (ไม่ต้องใช้ ICMP/CAP_NET_RAW)"""
    # ลอง TCP connect หลาย port (Windows: RDP 3389, SMB 445, HTTP 80)
    check_ports = [3389, 445, 80, 22, 443, 135]
    import time
    for port in check_ports:
        try:
            t0 = time.monotonic()
            with socket.create_connection((ip, port), timeout=1.5):
                latency = round((time.monotonic() - t0) * 1000, 1)
                return {"ip": ip, "online": True, "latency_ms": latency, "port": port}
        except (socket.timeout, ConnectionRefusedError, OSError):
            continue
        except Exception:
            continue

    # fallback: ลอง ping ถ้า subprocess พอใช้ได้
    try:
        result = subprocess.run(
            ["ping", "-c", "2", "-W", "1", ip],
            capture_output=True, text=True, timeout=6
        )
        if result.returncode == 0:
            return {"ip": ip, "online": True, "latency_ms": None}
    except Exception:
        pass

    return {"ip": ip, "online": False, "latency_ms": None}


# ── Keyword Detection ─────────────────────────────────────────────────────────

_DISK_KW    = {"disk", "storage", "พื้นที่", "ดิสก์", "เนื้อที่", "เต็ม", "ว่าง", "เหลือ"}
_DOCKER_KW  = {"docker", "container", "คอนเทนเนอร์", "service",
               "docker หยุดทำงาน", "service หยุดทำงาน",
               "หยุด container", "หยุด service",
               "docker รัน", "container รัน", "รัน container", "รัน docker"}
_WOL_KW     = {"เปิด pc", "เปิดpc", "wake", "wol", "ปลุก", "เปิดคอม"}
_PING_KW    = {"ping", "ออนไลน์", "online", "pc ออน", "pc เปิด", "pcเปิด", "pc อยู่ไหม"}
_NAS_KW     = {"nas", "synology", "เนส", "เซิร์ฟเวอร์บ้าน"}
# ถามถึงเครือข่าย/router → ping ทั้ง router+NAS+PC จริง (แทนการให้โมเดลเดา)
_NETWORK_KW = {"router", "เราเตอร์", "เครือข่าย", "network", "modem", "โมเด็ม", "gateway", "อุปกรณ์ในเครือข่าย"}


# guard กันโมเดล (โดยเฉพาะตัวเล็ก) เอาข้อมูลจริงไปห่อเป็น 'ผล ping ปลอม'
# วางติดท้ายข้อมูลที่ฉีด → ใกล้ attention โมเดลกว่า system prompt ที่อยู่ไกล
_TOOL_GUARD = (
    "\n\n⚠️ [กติกาเหล็กของข้อมูลด้านบน] นี่คือผลจริงทั้งหมดที่ระบบดึงได้ ณ ตอนนี้ — "
    "ห้ามแต่ง/เดา IP, response time, ผล ping, ชื่ออุปกรณ์ หรือสถานะอื่นที่ไม่มีด้านบนเด็ดขาด. "
    "อุปกรณ์ที่พี่ปอยถามแต่ไม่มีข้อมูลด้านบน (เช่น router/modem) = ระบบยังไม่ได้เช็ค "
    "ให้บอกตรงๆ ว่า 'ยังไม่ได้เช็ค <อุปกรณ์>' อย่าสร้างผล ping ปลอมขึ้นมา. "
    "ตอบโดยอ้างอิงเฉพาะตัวเลขด้านบนเท่านั้น. "
    "ห้ามแสดงคำสั่ง/โค้ด (เช่น `ping -c 3`) หรือตัวอย่าง output สมมติ (เช่น 'time=0.048ms') เด็ดขาด — "
    "พี่ปอยต้องการ 'ผลสรุปจริงสั้นๆ' ไม่ใช่ตัวอย่างการใช้คำสั่ง"
)


def ping_network() -> list[dict]:
    """ping Router+NAS+PC จริง → [{name, ip, online, latency_ms}] (ใช้ทั้ง narration + agent tool)"""
    results = []
    for name, ip in [("Router", ROUTER_IP), ("NAS", NAS_IP), ("PC", PC_IP)]:
        r = ping_device(ip)
        results.append({
            "name": name, "ip": ip,
            "online": r.get("online", False), "latency_ms": r.get("latency_ms"),
        })
    return results


def _format_ping_results(results: list[dict]) -> str:
    """format ผล ping จริงเป็น context (results = [{name, ip, online, latency_ms?}])"""
    lines = ["[ผล ping จริง — TCP check ณ ตอนนี้]"]
    for r in results:
        if r.get("online"):
            lat = f" ({r['latency_ms']}ms)" if r.get("latency_ms") is not None else ""
            lines.append(f"• {r['name']} ({r['ip']}): 🟢 Online{lat}")
        else:
            lines.append(f"• {r['name']} ({r['ip']}): 🔴 ไม่ตอบสนอง (offline หรือ block port)")
    return "\n".join(lines)


def _join_with_guard(parts: list[str]) -> str:
    """รวม parts + แนบ guard ท้ายสุด (ถ้ามีข้อมูล) — แยกเป็น pure fn เพื่อเทสได้"""
    if not parts:
        return ""
    return "\n\n".join(parts) + _TOOL_GUARD


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
    # network → ping router+NAS+PC จริง; ไม่งั้น ping PC อย่างเดียว (กัน ping ซ้ำ)
    if any(kw in p for kw in _NETWORK_KW):
        tools.append("ping_network")
    elif any(kw in p for kw in _PING_KW):
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

        elif tool == "ping_network":
            parts.append(_format_ping_results(ping_network()))

    return _join_with_guard(parts)
