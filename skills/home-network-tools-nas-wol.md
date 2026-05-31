# Home Network Tools — NAS Synology + WOL + Ping

`utils/home_tools.py` — ดึง real-time data จากเครือข่ายบ้าน inject เข้า chat context อัตโนมัติเมื่อ prompt มี keyword ที่เกี่ยวข้อง

## ตัวแปร env

```env
NAS_IP=192.168.51.49
NAS_PORT=5000
NAS_USER=...
NAS_PASS=...
PC_IP=192.168.51.235
PC_MAC=xx:xx:xx:xx:xx:xx   # สำหรับ Wake-on-LAN
ROUTER_IP=             # ไม่ตั้ง = เดาจาก subnet ของ NAS_IP (x.y.z.1) ผ่าน _default_gateway()
```

## ฟังก์ชันหลัก

| Function | Description | API ที่ใช้ |
|---|---|---|
| `nas_disk_usage()` | volume size, used %, hot/cold storage | DSM `SYNO.Core.Storage.Volume` (v7) / `SYNO.Storage.CGI.Storage` (v6 fallback) |
| `nas_docker_status()` | container list + state | DSM Container Manager API |
| `nas_system_info()` | CPU, RAM, uptime, temp | DSM `SYNO.Core.System` |
| `home_status_all()` | รวมทุกอย่างใน 1 call | combined |
| `wol_pc()` | ปลุก PC ผ่าน WOL magic packet | UDP broadcast :9 |
| `ping_device(ip)` | online check (generic, ใช้ IP ไหนก็ได้) | **TCP port check** (3389/445/80/22/443/135) — ไม่ใช้ ICMP (ไม่ต้อง CAP_NET_RAW) |
| `ping_network` (tool) | ping **Router+NAS+PC พร้อมกัน** จริง | เรียก `ping_device` ×3 → `_format_ping_results()` |
| `_default_gateway(ip)` | เดา router IP จาก subnet (x.y.z.1) | pure |

## Auto-injection ใน Chat

`detect_home_tools(prompt: str) -> list[str]` ตรวจ keyword:

| Keyword (ไทย/อังกฤษ) | Trigger tool |
|---|---|
| nas, ดิสก์, disk, storage, volume | `nas_disk_usage` |
| docker, container | `nas_docker_status` |
| ระบบ, system, cpu, ram | `nas_system_info` |
| pc, คอม, เปิดเครื่อง, wake | `wol` |
| **router, เราเตอร์, เครือข่าย, network, modem, gateway** | **`ping_network`** (ping router+NAS+PC จริง) |
| ping, ออนไลน์, online (ไม่มี network kw) | `ping_pc` (PC อย่างเดียว) |

→ ถ้าตรวจเจอ → `build_tool_context()` รวมผลลัพธ์ → inject เข้า system prompt ก่อนเรียก AI

## ⚠️ Anti-fabrication guard (สำคัญ — session 2026-05-31)
`build_tool_context()` ต่อท้ายข้อมูลที่ฉีดทุกครั้งด้วย **`_TOOL_GUARD`** (ผ่าน `_join_with_guard`):
> "นี่คือผลจริงทั้งหมด — ห้ามแต่ง IP/ping/คำสั่ง/output สมมติ, อุปกรณ์ที่ไม่มีข้อมูล = 'ยังไม่ได้เช็ค'"

เพราะโมเดลเล็กชอบเอาข้อมูลจริงไป **ห่อเป็นผล ping ปลอม** (เช่น `time=0.048ms` สมมติ).
guard ติดข้อมูล (ใกล้ attention) ได้ผลกว่า system prompt. **แต่ปิดไม่ได้ 100%** บนโมเดลเล็ก
→ งานที่ต้องการเป๊ะ ใช้ Agent mode (ดู `anti-hallucination-local-llm`)

## REST Endpoints

```
GET  /api/tools/home/disk        → nas_disk_usage()
GET  /api/tools/home/docker      → nas_docker_status()
GET  /api/tools/home/sysinfo     → nas_system_info()
GET  /api/tools/home/ping/{ip}   → ping_device(ip)   ← มีอยู่แล้ว! ใช้ wire เข้า Agent ได้เลย
POST /api/tools/home/wol         → wol_pc()
```
(prefix จริง = `/api/tools/home` — เดิม doc เขียน `/api/tools` ผิด)

## Error Handling

- ถ้า `NAS_USER`/`NAS_PASS` ไม่ตั้ง → คืน `{"error": "ยังไม่ตั้งค่า..."}`
- Session SID ถูกล็อกเอ๊าต์ทุกครั้งหลังใช้ (กัน leak)
- DSM v7 API ลองก่อน → fallback v6 ถ้า v7 ไม่รองรับ
- Timeout 8-12s ต่อ call

## Use Case ตัวอย่าง

```
User: "NAS ดิสก์เต็มแค่ไหนแล้ว"
   ↓ detect_home_tools() → ['nas_disk_usage']
   ↓ build_tool_context() ดึงจาก NAS API
   ↓ inject เข้า system prompt:
     [ข้อมูลจากบ้านแบบ Real-time]
     Volume 1: ใช้ไป 234GB / 2TB (12%) ...
   ↓ AI ตอบตามตัวเลขจริง
```
