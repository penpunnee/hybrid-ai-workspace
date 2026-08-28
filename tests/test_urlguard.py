"""เทส utils/urlguard.py — เกราะ SSRF ของ tool fetch_url

กลไกโจมตี 4 แบบจาก vault ssrf-safe-url-fetch.md:
  1. URL ภายในตรงๆ (private/loopback/link-local/reserved, decimal IP, [::1])
  2. redirect ไปข้างใน — ต้อง validate ทุก hop
  3. DNS rebinding — resolve ครั้งเดียวแล้ว pin IP ที่ต่อจริง
  4. scheme แปลก (file:// ftp:// gopher://)
"""
import socket

import pytest

from utils import urlguard
from utils.urlguard import (
    URLBlockedError,
    URLFetchError,
    fetch_url_safe,
    resolve_and_validate,
)

PUBLIC_IP = "93.184.216.34"   # example.com


def _fake_getaddrinfo(mapping):
    """สร้าง getaddrinfo ปลอม — mapping: hostname → list[ip]"""
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host in mapping:
            return [
                (socket.AF_INET6 if ":" in ip else socket.AF_INET,
                 socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in mapping[host]
            ]
        return real(host, port, *args, **kwargs)

    return fake


# ── 1+4: resolve_and_validate ────────────────────────────────────────────────

class TestSchemeAllowlist:
    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/",
        "javascript:alert(1)",
        "example.com/no-scheme",
    ])
    def test_scheme_นอก_http_https_ถูกบล็อก(self, url):
        with pytest.raises(URLBlockedError):
            resolve_and_validate(url)


class TestPrivateIPBlocked:
    @pytest.mark.parametrize("url", [
        "http://192.168.51.1/",          # router ในบ้าน
        "http://10.0.0.5/",
        "http://172.16.0.1:5000/",
        "http://127.0.0.1:8080/api",     # ตัว backend เอง
        "http://[::1]/",                 # IPv6 loopback
        "http://169.254.169.254/latest/meta-data/",  # link-local / cloud metadata
        "http://3232248577/",            # decimal ของ 192.168.51.1
        "http://0.0.0.0/",
    ])
    def test_IP_ภายในตรงๆ_ถูกบล็อก(self, url):
        with pytest.raises(URLBlockedError):
            resolve_and_validate(url)

    def test_localhost_ถูกบล็อก(self):
        with pytest.raises(URLBlockedError):
            resolve_and_validate("http://localhost:8080/")

    def test_hostname_ที่_resolve_เป็น_private_ถูกบล็อก(self, monkeypatch):
        # DNS ของผู้โจมตีชี้โดเมนเข้า LAN
        monkeypatch.setattr(
            socket, "getaddrinfo",
            _fake_getaddrinfo({"evil.example": ["192.168.51.49"]}))
        with pytest.raises(URLBlockedError):
            resolve_and_validate("http://evil.example/")

    def test_resolve_ได้ทั้ง_public_และ_private_ก็ต้องบล็อก(self, monkeypatch):
        # ตัวใดตัวหนึ่ง private = บล็อกทั้ง URL (ห้ามเลือกตัวที่ผ่าน)
        monkeypatch.setattr(
            socket, "getaddrinfo",
            _fake_getaddrinfo({"mixed.example": [PUBLIC_IP, "10.0.0.1"]}))
        with pytest.raises(URLBlockedError):
            resolve_and_validate("http://mixed.example/")

    def test_userinfo_ใน_URL_ถูกบล็อก(self):
        with pytest.raises(URLBlockedError):
            resolve_and_validate("http://user:pass@example.com/")


class TestPublicAllowed:
    def test_hostname_public_ผ่าน_และคืน_IP_ที่ตรวจแล้ว(self, monkeypatch):
        monkeypatch.setattr(
            socket, "getaddrinfo",
            _fake_getaddrinfo({"example.com": [PUBLIC_IP]}))
        ips = resolve_and_validate("https://example.com/page")
        assert ips == [PUBLIC_IP]

    def test_resolve_ไม่ได้_ถือเป็น_fetch_error(self, monkeypatch):
        def boom(*a, **k):
            raise socket.gaierror("NXDOMAIN")
        monkeypatch.setattr(socket, "getaddrinfo", boom)
        with pytest.raises(URLFetchError):
            resolve_and_validate("http://nxdomain.example/")


# ── 2+3: fetch_url_safe — pin IP + เดิน redirect เอง ─────────────────────────

class _FakeResponse:
    def __init__(self, status=200, headers=None, body=b"", chunk=8192):
        self.status = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self._body = body
        self.released = False

    def stream(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def release_conn(self):
        self.released = True


class _FakePool:
    """จำ argument ที่ถูกเปิด + คิว response ที่จะตอบ"""
    opened: list = []          # (scheme, ip, port, hostname)
    responses: list = []       # FIFO
    requests: list = []        # (method, path, headers)

    def __init__(self, scheme, ip, port, hostname):
        self.scheme = scheme

    def urlopen(self, method, path, headers=None, **kwargs):
        _FakePool.requests.append((method, path, headers or {}))
        return _FakePool.responses.pop(0)

    def close(self):
        pass


@pytest.fixture
def fake_pool(monkeypatch):
    _FakePool.opened = []
    _FakePool.responses = []
    _FakePool.requests = []

    def opener(scheme, ip, port, hostname, timeout):
        _FakePool.opened.append((scheme, ip, port, hostname))
        return _FakePool(scheme, ip, port, hostname)

    monkeypatch.setattr(urlguard, "_open_pool", opener)
    return _FakePool


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo({
            "example.com": [PUBLIC_IP],
            "other.example": ["1.1.1.1"],
        }))


class TestFetchPinsIP:
    def test_ต่อที่_IP_ที่ตรวจแล้ว_พร้อม_Host_header_โดเมนเดิม(self, fake_pool, public_dns):
        fake_pool.responses = [_FakeResponse(body="<p>สวัสดี</p>".encode())]
        res = fetch_url_safe("https://example.com/page?q=1")
        # pin: pool เปิดที่ IP ไม่ใช่ hostname
        assert fake_pool.opened == [("https", PUBLIC_IP, 443, "example.com")]
        method, path, headers = fake_pool.requests[0]
        assert method == "GET"
        assert path == "/page?q=1"
        assert headers["Host"] == "example.com"
        assert "สวัสดี" in res.text

    def test_port_ไม่มาตรฐาน_ติดไปกับ_Host_header(self, fake_pool, public_dns):
        fake_pool.responses = [_FakeResponse(body=b"ok", headers={"content-type": "text/plain"})]
        fetch_url_safe("http://example.com:8081/x")
        assert fake_pool.opened == [("http", PUBLIC_IP, 8081, "example.com")]
        assert fake_pool.requests[0][2]["Host"] == "example.com:8081"


class TestRedirects:
    def test_เดิน_redirect_เอง_และ_validate_hop_ปลายทาง(self, fake_pool, public_dns):
        fake_pool.responses = [
            _FakeResponse(status=302, headers={"location": "https://other.example/final"}),
            _FakeResponse(body=b"final"),
        ]
        res = fetch_url_safe("https://example.com/start")
        assert [o[1] for o in fake_pool.opened] == [PUBLIC_IP, "1.1.1.1"]
        assert res.text == "final"
        assert res.url == "https://other.example/final"

    def test_redirect_เข้า_LAN_ถูกบล็อก(self, fake_pool, public_dns):
        # เว็บนอกตอบ 302 → NAS ในบ้าน = กลไกโจมตีข้อ 2
        fake_pool.responses = [
            _FakeResponse(status=302, headers={"location": "http://192.168.51.49:5000/webapi"}),
        ]
        with pytest.raises(URLBlockedError):
            fetch_url_safe("https://example.com/start")

    def test_redirect_relative_ก็ตาม_และ_validate(self, fake_pool, public_dns):
        fake_pool.responses = [
            _FakeResponse(status=301, headers={"location": "/moved"}),
            _FakeResponse(body=b"moved"),
        ]
        res = fetch_url_safe("https://example.com/old")
        assert res.url == "https://example.com/moved"

    def test_redirect_เกินเพดาน_ตัดทิ้ง(self, fake_pool, public_dns):
        fake_pool.responses = [
            _FakeResponse(status=302, headers={"location": "https://example.com/a"})
            for _ in range(10)
        ]
        with pytest.raises(URLFetchError):
            fetch_url_safe("https://example.com/start", max_redirects=3)
        # 1 request แรก + ตาม redirect ได้อีก 3 = 4 พอดี
        assert len(fake_pool.requests) == 4


class TestBodyLimits:
    def test_body_เกิน_cap_ถูกตัดและติดธง_truncated(self, fake_pool, public_dns):
        fake_pool.responses = [_FakeResponse(body=b"a" * 5000)]
        res = fetch_url_safe("https://example.com/big", max_bytes=1000)
        assert res.truncated is True
        assert len(res.text) <= 1000

    def test_content_type_นอก_allowlist_ถูกปฏิเสธ(self, fake_pool, public_dns):
        fake_pool.responses = [_FakeResponse(
            headers={"content-type": "application/octet-stream"}, body=b"\x00\x01")]
        with pytest.raises(URLFetchError):
            fetch_url_safe("https://example.com/file.bin")

    def test_status_ไม่_200_ถือเป็น_error(self, fake_pool, public_dns):
        fake_pool.responses = [_FakeResponse(status=404, body=b"nope")]
        with pytest.raises(URLFetchError):
            fetch_url_safe("https://example.com/missing")

    def test_decode_ตาม_charset_ใน_header(self, fake_pool, public_dns):
        fake_pool.responses = [_FakeResponse(
            headers={"content-type": "text/html; charset=tis-620"},
            body="ไทย".encode("tis-620"))]
        res = fetch_url_safe("https://example.com/thai")
        assert "ไทย" in res.text


# ── 3: tool fetch_url ใน registry ────────────────────────────────────────────

class TestFetchUrlTool:
    def test_ลงทะเบียนใน_registry(self):
        from agents.tools import _ALL_TOOLS
        assert "fetch_url" in _ALL_TOOLS
        spec = _ALL_TOOLS["fetch_url"]
        assert "url" in spec["parameters"]["properties"]
        assert spec["parameters"]["required"] == ["url"]

    def test_ผลลัพธ์เป็น_text_ที่สกัดจาก_HTML(self, monkeypatch):
        from agents import tools as agent_tools
        monkeypatch.setattr(
            urlguard, "fetch_url_safe",
            lambda url, **k: urlguard.FetchResult(
                url=url, content_type="text/html",
                text="<html><script>x()</script><p>เนื้อหาจริง</p></html>",
                truncated=False))
        out = agent_tools._t_fetch_url("https://example.com/a")
        assert "เนื้อหาจริง" in out
        assert "x()" not in out          # script ถูกตัดโดย _extract_text
        assert "example.com/a" in out    # บอกที่มา

    def test_URL_ถูกบล็อก_ตอบข้อความอธิบาย_ไม่_raise(self, monkeypatch):
        from agents import tools as agent_tools

        def blocked(url, **k):
            raise URLBlockedError("ปลายทางเป็น IP ภายใน")
        monkeypatch.setattr(urlguard, "fetch_url_safe", blocked)
        out = agent_tools._t_fetch_url("http://192.168.51.1/")
        assert "ไม่" in out or "❌" in out
        assert "ปลายทางเป็น IP ภายใน" in out

    def test_เนื้อหา_json_ไม่ผ่าน_extract_html(self, monkeypatch):
        from agents import tools as agent_tools
        monkeypatch.setattr(
            urlguard, "fetch_url_safe",
            lambda url, **k: urlguard.FetchResult(
                url=url, content_type="application/json",
                text='{"key": "ค่า"}', truncated=False))
        out = agent_tools._t_fetch_url("https://example.com/api.json")
        assert '"key"' in out


# ── 4: เส้น _fetch_url ของ web_search ใช้เกราะเดียวกัน ───────────────────────

class TestWebsearchUsesGuard:
    def test_fetch_url_ของ_websearch_บล็อก_IP_ภายใน(self):
        from utils import websearch
        # ต้องคืน "" (best effort เดิม) ไม่ throw และไม่ยิงจริง
        assert websearch._fetch_url("http://192.168.51.1/") == ""
