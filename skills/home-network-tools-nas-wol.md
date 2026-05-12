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
```

## ฟังก์ชันหลัก

| Function | Description | API ที่ใช้ |
|---|---|---|
| `nas_disk_usage()` | volume size, used %, hot/cold storage | DSM `SYNO.Core.Storage.Volume` (v7) / `SYNO.Storage.CGI.Storage` (v6 fallback) |
| `nas_docker_status()` | container list + state | DSM Container Manager API |
| `nas_system_info()` | CPU, RAM, uptime, temp | DSM `SYNO.Core.System` |
| `home_status_all()` | รวมทุกอย่างใน 1 call | combined |
| `wol_pc()` | ปลุก PC ผ่าน WOL magic packet | UDP broadcast :9 |
| `ping_device(ip)` | ping/jitter check | `subprocess: ping` |

## Auto-injection ใน Chat

`detect_home_tools(prompt: str) -> list[str]` ตรวจ keyword:

| Keyword (ไทย/อังกฤษ) | Trigger tool |
|---|---|
| nas, ดิสก์, disk, storage, volume | `nas_disk_usage` |
| docker, container | `nas_docker_status` |
| ระบบ, system, cpu, ram | `nas_system_info` |
| pc, คอม, เปิดเครื่อง, wake | `wol_pc` หรือ `ping` |
| ping, ตอบไหม, online | `ping_device` |

→ ถ้าตรวจเจอ → `build_tool_context()` รวมผลลัพธ์ → inject เข้า system prompt ก่อนเรียก AI

## REST Endpoints

```
GET  /api/tools/disk        → nas_disk_usage()
GET  /api/tools/docker      → nas_docker_status()
GET  /api/tools/sysinfo     → nas_system_info()
GET  /api/tools/ping/{ip}   → ping_device(ip)
POST /api/tools/wol         → wol_pc()
```

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
