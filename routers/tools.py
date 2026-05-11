import re
from fastapi import APIRouter, Request
from utils.home_tools import (
    nas_disk_usage, nas_docker_status, nas_system_info,
    home_status_all, wol_pc, ping_device,
)

router = APIRouter(prefix="/api/tools/home", tags=["tools"])


@router.get("/status")
def home_status():
    return home_status_all()


@router.get("/disk")
def home_disk():
    return nas_disk_usage()


@router.get("/docker")
def home_docker():
    return nas_docker_status()


@router.get("/sysinfo")
def home_sysinfo():
    return nas_system_info()


@router.post("/wol")
async def home_wol(request: Request):
    return wol_pc()


@router.get("/ping/{ip}")
def home_ping(ip: str):
    if not re.match(r"^[\d.]+$", ip):
        return {"error": "IP ไม่ถูกต้อง"}
    return ping_device(ip)
