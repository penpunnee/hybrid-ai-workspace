# UI Keyboard Shortcuts & Features

## Keyboard Shortcuts

| Shortcut | การทำงาน |
|---|---|
| `Enter` | ส่งข้อความ |
| `Shift+Enter` | ขึ้นบรรทัดใหม่ |
| `↑` (ใน input) | ดึง prompt ก่อนหน้า |
| `↓` (ใน input) | ดึง prompt ถัดไป |
| `Ctrl+K` / `^K` | ค้นหาประวัติแชท (Global Search) |
| `Ctrl+Shift+F` | เปิด Global Search |
| `Ctrl+E` | Export แชทเป็น .md |
| `Ctrl+V` | Paste รูปภาพจาก clipboard |
| `Cmd+Shift+R` | Hard refresh (ล้าง cache) |

## ปุ่มใน Header (บนขวา)

| ไอคอน | การทำงาน |
|---|---|
| 🧩 | Multi-AI Debate Mode (3 AI ตอบพร้อมกัน) |
| 🌙 | Obsidian Mode (inject vault notes) |
| 🔗 | Share Chat Link |
| 💾 | Export แชท |
| 🔔 | Toggle notifications |
| 🤖 | Agent Mode (Gemini + Google Search) |
| 🎙️ | Voice Mode |
| 🔊 | Text-to-Speech toggle |
| 📊 | Usage Dashboard |
| 🗑️ | Clear session |

## ปุ่มบน Chat Bubble (hover)

- **📋 Copy** — copy ข้อความทั้ง bubble
- **📌 Pin** — pin ข้อความสำคัญ (ขอบทอง)
- **✏️ Edit** — แก้ prompt + resend
- **🔄 Regenerate** — ให้ AI ตอบใหม่

## FAB Buttons (มุมขวาล่าง)

| ปุ่ม | การทำงาน |
|---|---|
| 🏠 | Home Control Panel (NAS + PC + Docker) |
| ⬇️ | Scroll to bottom |
| ⏹️ | Stop generation (ขณะ AI กำลังตอบ) |

## Home Control Panel (🏠)

- **💾 NAS Storage** — disk usage + progress bar
- **🐳 Docker Containers** — รายการ + สถานะ running/stopped
- **🖥️ PC Status** — online/offline + latency
- **🔄 Refresh** — อัปเดตข้อมูลใหม่
- **⚡ Wake PC** — ส่ง Wake-on-LAN ไปยัง PC
- **📡 Ping NAS** — ตรวจการเชื่อมต่อ NAS

## Token Bar (ล่างซ้าย input)

- แสดง % ของ context window ที่ใช้ไป
- ประมาณจากจำนวนตัวอักษร (0.35 chars/token)
- สีแดง = ใกล้เต็ม context

## Prompt Templates (ปุ่มบน input)

แต่ละ AI มี shortcut templates:
- **ฟ้า**: 🎨 ออกแบบ UI, 🔍 Review โค้ด, 📱 Responsive, ⚡ Optimize
- **ขวัญ**: 🐛 หา Bug, 💡 ระดมไอเดีย, 📊 วิเคราะห์, 🏗️ วางแผน
- **ขิม**: 📋 สรุป Bullet, 🗺️ สร้าง Roadmap, 📝 เขียน README, 📅 Meeting Notes
