"""URL guard — เกราะ SSRF สำหรับดึง URL ที่มาจากบทสนทนา (tool fetch_url)

backend รันในบ้าน (NAS วง 192.168.51.0/24) — ถ้า fetch URL โดยไม่กรอง
prompt injection สั่งขวัญยิง router/DSM/Pi-hole/ChromaDB/ตัว backend เองได้
กลไกโจมตี 4 แบบที่ปิด (vault ssrf-safe-url-fetch.md):
  1. URL ภายในตรงๆ            → resolve ทุก IP (A+AAAA) แล้วเช็คด้วย ipaddress
  2. redirect ไปข้างใน          → allow_redirects=False เดินเองทีละ hop validate ทุก hop
  3. DNS rebinding (TOCTOU)    → pin IP: ต่อที่ IP ที่ validate แล้ว + Host header โดเมนเดิม
                                 ฝั่ง HTTPS เช็ค cert กับโดเมนเดิมผ่าน assert_hostname
                                 (แนวแพตช์ AutoGPT GHSA-wvjg-9879-3m7w)
  4. scheme แปลก               → รับเฉพาะ http/https
เกราะเสริม: GET เท่านั้น · ไม่ส่ง credential/cookie · stream + cap ขนาด · timeout สั้น
· content-type allowlist (html/text/json/xml)
"""
import ipaddress
import logging
import re
import socket
from typing import NamedTuple
from urllib.parse import urljoin, urlsplit

logger = logging.getLogger(__name__)


class URLBlockedError(ValueError):
    """URL ถูกปฏิเสธด้วยเหตุผลความปลอดภัย — ห้าม retry/เลี่ยง"""


class URLFetchError(RuntimeError):
    """ดึงไม่สำเร็จด้วยเหตุผลปกติ (resolve ไม่ได้ / HTTP error / content-type ผิด)"""


class FetchResult(NamedTuple):
    url: str            # URL สุดท้ายหลังตาม redirect
    content_type: str
    text: str
    truncated: bool


_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_CONTENT = ("html", "text", "json", "xml")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
DEFAULT_TIMEOUT = 6          # วินาที — เท่ากับ _FETCH_TIMEOUT ของ websearch
DEFAULT_MAX_BYTES = 1_000_000
DEFAULT_MAX_REDIRECTS = 3

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def resolve_and_validate(url: str) -> list[str]:
    """resolve ทุก IP ของ URL แล้วตรวจ — คืน list IP ที่ปลอดภัย (IPv4 ขึ้นก่อน)

    raise URLBlockedError ถ้า scheme ผิด / มี userinfo / IP ใดเป็น
    private/loopback/link-local/reserved (ตัวเดียวไม่ผ่าน = บล็อกทั้ง URL)
    """
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise URLBlockedError(f"รับเฉพาะ http/https (ได้ {parts.scheme or 'ไม่มี scheme'!r})")
    if parts.username or parts.password:
        raise URLBlockedError("ไม่รับ URL ที่มี user:pass@ ฝังอยู่")
    host = parts.hostname
    if not host:
        raise URLBlockedError("URL ไม่มี hostname")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as e:
        raise URLBlockedError(f"port ไม่ถูกต้อง: {e}") from e

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise URLFetchError(f"resolve {host} ไม่ได้: {e}") from e

    ips: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise URLFetchError(f"resolve {host} ไม่ได้ IP เลย")

    for ip in ips:
        addr = ipaddress.ip_address(ip)
        # is_global เป็น False ครอบ private/loopback/link-local/reserved/CGNAT ทั้งหมด
        if not addr.is_global:
            raise URLBlockedError(f"ปลายทางเป็น IP ภายใน/สงวน ({host} → {ip})")

    # IPv4 ขึ้นก่อน — คอนเทนเนอร์บน NAS ไม่มี route IPv6
    ips.sort(key=lambda i: ":" in i)
    return ips


def _open_pool(scheme: str, ip: str, port: int, hostname: str, timeout: float):
    """เปิด connection pool ที่ต่อไปยัง IP ตรงๆ (pin) — แยกไว้ให้เทส mock ได้"""
    import certifi
    import urllib3
    t = urllib3.Timeout(connect=timeout, read=timeout)
    if scheme == "https":
        # ต่อที่ IP แต่ SNI + ตรวจ cert กับ "โดเมนเดิม" — กัน DNS rebinding
        return urllib3.HTTPSConnectionPool(
            host=ip, port=port, timeout=t, maxsize=1, retries=False,
            cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(),
            server_hostname=hostname, assert_hostname=hostname,
        )
    return urllib3.HTTPConnectionPool(host=ip, port=port, timeout=t, maxsize=1, retries=False)


def _decode(body: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w\-]+)", content_type)
    if m:
        try:
            return body.decode(m.group(1), errors="replace")
        except LookupError:
            pass
    return body.decode("utf-8", errors="replace")


def fetch_url_safe(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> FetchResult:
    """GET url อย่างปลอดภัย — validate + pin IP ทุก hop, เดิน redirect เอง, cap ขนาด"""
    current = url
    for _hop in range(max_redirects + 1):
        ips = resolve_and_validate(current)
        parts = urlsplit(current)
        hostname = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        host_header = hostname if parts.port is None else f"{hostname}:{parts.port}"
        path = parts.path or "/"
        if parts.query:
            path += f"?{parts.query}"

        pool = _open_pool(parts.scheme, ips[0], port, hostname, timeout)
        try:
            resp = pool.urlopen(
                "GET", path, redirect=False, preload_content=False,
                headers={
                    "Host": host_header,
                    "User-Agent": _UA,
                    "Accept": "text/html,application/json,text/*;q=0.9,*/*;q=0.5",
                    "Accept-Language": "th,en;q=0.9",
                },
            )
            if resp.status in _REDIRECT_STATUSES:
                location = resp.headers.get("location")
                resp.release_conn()
                if not location:
                    raise URLFetchError(f"HTTP {resp.status} แต่ไม่มี Location header")
                # ไม่พก header อ่อนไหวข้าม hop (เราไม่ส่ง credential อยู่แล้ว) —
                # แค่เดินต่อแล้ว validate ปลายทางใหม่ด้วยกติกาเดียวกับ hop แรก
                current = urljoin(current, location)
                continue
            if resp.status != 200:
                resp.release_conn()
                raise URLFetchError(f"HTTP {resp.status}")

            content_type = (resp.headers.get("content-type") or "").lower()
            if not any(t in content_type for t in _ALLOWED_CONTENT):
                resp.release_conn()
                raise URLFetchError(f"content-type ไม่รองรับ: {content_type or 'ไม่ระบุ'}")

            body = b""
            truncated = False
            for chunk in resp.stream(8192):
                body += chunk
                if len(body) >= max_bytes:
                    body = body[:max_bytes]
                    truncated = True
                    break
            resp.release_conn()
            return FetchResult(
                url=current, content_type=content_type,
                text=_decode(body, content_type), truncated=truncated,
            )
        finally:
            pool.close()

    raise URLFetchError(f"redirect เกิน {max_redirects} ครั้ง")
