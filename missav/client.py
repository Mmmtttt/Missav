"""
MissAV/Jable extract and proxy client.
"""

from __future__ import annotations

import base64
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

from curl_cffi import requests as cffi_requests


_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_PROXY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_EXCLUDED_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection"}
_M3U8_STREAM_PATTERN = re.compile(r"#EXT-X-STREAM-INF:BANDWIDTH=(\d+),.*?RESOLUTION=(\d+x\d+).*?\n(.*)")
_M3U8_KEY_PATTERN = re.compile(r'#EXT-X-KEY:METHOD=([^,]+),URI="([^"]+)"')
_JABLE_HLS_PATTERN = re.compile(r"var\s+hlsUrl\s*=\s*'(https?://[^']+)'")
_CHALLENGE_TEXT_MARKERS = (
    "Just a moment...",
    "Enable JavaScript and cookies to continue",
    "/cdn-cgi/challenge-platform/",
)
_JABLE_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
]
_JABLE_BROWSER_CONTEXT = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "viewport": {"width": 1280, "height": 800},
    "locale": "zh-CN",
}


@dataclass
class ProxyStreamResponse:
    status_code: int
    headers: List[Tuple[str, str]]
    body: Iterable[bytes]


@dataclass
class ProxyContentResponse:
    status_code: int
    headers: List[Tuple[str, str]]
    content: bytes


class MissavClient:
    def __init__(
        self,
        proxy_base_path: str = "/api/v1/video",
        timeout_seconds: int = 30,
        impersonate: str = "chrome120",
        javdb_cookie_header: str = "",
    ):
        self.proxy_base_path = proxy_base_path.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.impersonate = impersonate
        self.javdb_cookie_header = str(javdb_cookie_header or "").strip()

    def _request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str] = None,
        stream: bool = False,
        timeout: int = None,
        allow_redirects: bool = True,
        impersonate: str = None,
    ):
        from curl_cffi import requests as cffi_requests

        timeout = timeout or self.timeout_seconds
        impersonate = impersonate or self.impersonate

        return cffi_requests.request(
            method,
            url,
            headers=headers or {},
            stream=stream,
            timeout=timeout,
            allow_redirects=allow_redirects,
            impersonate=impersonate,
        )

    def build_sources(self, avid: str) -> List[Dict]:
        sources: List[Dict] = []

        extractors = (
            ("MissAV", "missav", self.extract_from_missav),
        )
        for source_name, source_id, extractor in extractors:
            try:
                result, error = extractor(avid)
                if result:
                    sources.append(
                        {
                            "name": source_name,
                            "source": source_id,
                            "streams": result.get("streams", []),
                            "page_url": result.get("page_url", ""),
                            "available": True,
                        }
                    )
                else:
                    sources.append(
                        {
                            "name": source_name,
                            "source": source_id,
                            "available": False,
                            "error": error,
                        }
                    )
            except Exception as exc:
                sources.append(
                    {
                        "name": source_name,
                        "source": source_id,
                        "available": False,
                        "error": str(exc),
                    }
                )

        return sources

    def extract_from_missav(self, avid: str, domain: str = "missav.ai") -> Tuple[Optional[Dict], Optional[str]]:
        headers = {**_PAGE_HEADERS, "Referer": f"https://{domain}/"}

        urls = [
            f"https://{domain}/cn/{avid}-chinese-subtitle".lower(),
            f"https://{domain}/cn/{avid}-uncensored-leak".lower(),
            f"https://{domain}/cn/{avid}".lower(),
        ]

        html = None
        page_url = None
        last_status = None
        last_exc = None
        for url in urls:
            for attempt in range(3):
                try:
                    resp = cffi_requests.get(url, headers=headers, timeout=15, impersonate=self.impersonate)
                    last_status = resp.status_code
                    if resp.status_code == 200:
                        html = resp.text
                        page_url = url
                        break
                    # Cloudflare challenge / rate limit: back off and retry
                    time.sleep(1.5 * (attempt + 1))
                except Exception as exc:
                    last_exc = exc
                    time.sleep(1.0 * (attempt + 1))
            if html:
                break

        if not html:
            if last_exc is not None:
                return None, f"无法获取页面: {last_exc}"
            if last_status is not None:
                return None, f"无法获取页面 (HTTP {last_status})"
            return None, "无法获取页面"

        uuid = None
        match = re.search(r"m3u8\|([a-f0-9\|]+)\|com\|surrit\|https\|video", html)
        if match:
            uuid = "-".join(match.group(1).split("|")[::-1])
        else:
            match = re.search(r"surrit\.com/([a-f0-9-]+)", html)
            if match:
                uuid = match.group(1)

        if not uuid:
            return None, "未找到视频源"

        playlist_url = f"https://surrit.com/{uuid}/playlist.m3u8"

        try:
            surrit_headers = {
                **_PAGE_HEADERS,
                "Origin": "https://missav.ai",
                "Referer": "https://missav.ai/",
            }
            playlist_response = cffi_requests.get(
                playlist_url,
                headers=surrit_headers,
                timeout=10,
                impersonate=self.impersonate,
            )
            if playlist_response.status_code != 200:
                return None, "无法获取播放列表"

            streams = []
            for match in _M3U8_STREAM_PATTERN.finditer(playlist_response.text):
                stream_url = match.group(3).strip()
                if not stream_url.startswith("http"):
                    stream_url = urljoin(f"https://surrit.com/{uuid}/", stream_url)

                parsed_stream = urlparse(stream_url)
                proxy_url = f"/proxy/surrit.com{parsed_stream.path}"
                if parsed_stream.query:
                    proxy_url = f"{proxy_url}?{parsed_stream.query}"

                streams.append(
                    {
                        "bandwidth": int(match.group(1)),
                        "resolution": match.group(2),
                        "url": stream_url,
                        "proxy_url": proxy_url,
                    }
                )

            if not streams:
                return None, "未找到视频流"

            streams.sort(key=lambda x: x["bandwidth"], reverse=True)
            return (
                {
                    "avid": avid,
                    "uuid": uuid,
                    "streams": streams,
                    "playlist_url": playlist_url,
                    "page_url": page_url,
                    "source": "MissAV",
                },
                None,
            )
        except Exception as exc:
            return None, str(exc)

    def extract_from_jable(self, avid: str, domain: str = "jable.tv") -> Tuple[Optional[Dict], Optional[str]]:
        headers = {**_PAGE_HEADERS, "Referer": f"https://{domain}/"}
        page_url = f"https://{domain}/videos/{avid}/".lower()
        html = None
        browser_attempted = False
        last_error = ""

        try:
            resp = cffi_requests.get(page_url, headers=headers, timeout=15, impersonate=self.impersonate)
            html = resp.text if resp.status_code == 200 else ""
            if resp.status_code != 200:
                last_error = f"页面返回 {resp.status_code}"
            elif self._is_cloudflare_challenge_html(html):
                last_error = "页面被 Cloudflare challenge 拦截"
        except Exception as exc:
            last_error = f"请求失败: {exc}"

        match = self._extract_jable_hls_match(html)
        if match is None:
            browser_attempted = True
            html, browser_error = self._fetch_jable_page_with_playwright(page_url, headers=headers)
            if browser_error:
                return None, browser_error if not last_error else f"{last_error}; {browser_error}"
            match = self._extract_jable_hls_match(html)
        if not match:
            return None, "未找到 m3u8 链接"

        m3u8_url = match.group(1) if hasattr(match, "group") else str(match)
        try:
            m3u8_resp = cffi_requests.get(m3u8_url, headers=headers, timeout=10, impersonate=self.impersonate)
            if m3u8_resp.status_code != 200:
                return None, "无法获取 m3u8 内容"

            streams = []
            for match in _M3U8_STREAM_PATTERN.finditer(m3u8_resp.text):
                stream_url = match.group(3).strip()
                if not stream_url.startswith("http"):
                    stream_url = urljoin(m3u8_url, stream_url)
                streams.append(
                    {
                        "bandwidth": int(match.group(1)),
                        "resolution": match.group(2),
                        "url": stream_url,
                        "proxy_url": self._build_relative_proxy2_url(stream_url),
                    }
                )

            if streams:
                streams.sort(key=lambda x: x["bandwidth"], reverse=True)
            else:
                streams = [
                    {
                        "bandwidth": 0,
                        "resolution": "unknown",
                        "url": m3u8_url,
                        "proxy_url": self._build_relative_proxy2_url(m3u8_url),
                    }
                ]

            return (
                {
                    "avid": avid,
                    "streams": streams,
                    "m3u8_url": m3u8_url,
                    "page_url": page_url,
                    "source": "Jable",
                    "browser_fallback": browser_attempted,
                },
                None,
            )
        except Exception as exc:
            return None, str(exc)

    @staticmethod
    def _extract_jable_hls_match(html: Optional[str]):
        normalized_html = str(html or "")
        if not normalized_html:
            return None
        return _JABLE_HLS_PATTERN.search(normalized_html)

    @staticmethod
    def _is_cloudflare_challenge_html(html: Optional[str]) -> bool:
        normalized_html = str(html or "")
        if not normalized_html:
            return False
        return any(marker in normalized_html for marker in _CHALLENGE_TEXT_MARKERS)

    def _iter_jable_browser_launch_options(self):
        preferred_channel = str(os.getenv("ULTIMATE_JABLE_BROWSER_CHANNEL") or "").strip().lower()
        channels = []
        if preferred_channel:
            channels.append(preferred_channel)
        channels.extend(["msedge", "chrome", "chromium"])

        seen = set()
        for channel in channels:
            normalized = str(channel or "").strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)

            if normalized == "chromium":
                yield {"headless": True, "args": list(_JABLE_BROWSER_ARGS)}, "chromium"
            else:
                yield {"headless": True, "channel": normalized, "args": list(_JABLE_BROWSER_ARGS)}, normalized

    def _fetch_jable_page_with_playwright(self, page_url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[str], Optional[str]]:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            return None, f"Playwright 不可用: {exc}"

        extra_headers = {}
        if isinstance(headers, dict):
            referer = str(headers.get("Referer") or "").strip()
            accept_language = str(headers.get("Accept-Language") or "").strip()
            if referer:
                extra_headers["Referer"] = referer
            if accept_language:
                extra_headers["Accept-Language"] = accept_language

        attempts = []
        playwright = sync_playwright().start()
        try:
            for launch_options, label in self._iter_jable_browser_launch_options():
                browser = None
                context = None
                try:
                    browser = playwright.chromium.launch(**launch_options)
                    context_options = dict(_JABLE_BROWSER_CONTEXT)
                    if extra_headers:
                        context_options["extra_http_headers"] = dict(extra_headers)
                    context = browser.new_context(**context_options)
                    page = context.new_page()
                    page.add_init_script(
                        """
                        Object.defineProperty(navigator, 'webdriver', {
                          get: () => undefined
                        });
                        """
                    )
                    page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(8000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except PlaywrightTimeoutError:
                        pass

                    html = ""
                    for _ in range(4):
                        try:
                            html = page.content()
                        except Exception:
                            page.wait_for_timeout(2000)
                            continue

                        if self._extract_jable_hls_match(html):
                            return html, None
                        if not self._is_cloudflare_challenge_html(html):
                            break
                        page.wait_for_timeout(3000)

                    if html and self._extract_jable_hls_match(html):
                        return html, None
                    if self._is_cloudflare_challenge_html(html):
                        attempts.append(f"{label}: Cloudflare challenge 未通过")
                    else:
                        attempts.append(f"{label}: 页面已加载但未找到 hlsUrl")
                except Exception as exc:
                    attempts.append(f"{label}: {exc}")
                finally:
                    if context is not None:
                        try:
                            context.close()
                        except Exception:
                            pass
                    if browser is not None:
                        try:
                            browser.close()
                        except Exception:
                            pass
        finally:
            playwright.stop()

        return None, "; ".join(attempts) or "Playwright 未能获取到 Jable 页面"

    def proxy_stream(
        self,
        domain: str,
        path: str,
        query_string: str = "",
        incoming_referer: str = "",
    ) -> ProxyStreamResponse:
        target_url = f"https://{domain}/{path}"
        if query_string:
            target_url = f"{target_url}?{query_string}"

        headers = self._build_proxy_headers(domain, incoming_referer)
        resp = cffi_requests.get(
            target_url,
            headers=headers,
            stream=True,
            timeout=self.timeout_seconds,
            impersonate=self.impersonate,
        )

        resp_headers = self._filter_headers(resp.headers)

        def body_iter():
            try:
                for chunk in resp.iter_content(chunk_size=1024):
                    if chunk:
                        yield chunk
            finally:
                resp.close()

        return ProxyStreamResponse(status_code=resp.status_code, headers=resp_headers, body=body_iter())

    def proxy_url(
        self,
        method: str = "GET",
        query_string: str = "",
        body_url: str = "",
        incoming_referer: str = "",
        incoming_headers: Dict[str, str] = None,
    ) -> ProxyContentResponse:
        url = self._resolve_proxy2_url(method, query_string, body_url)
        if not url:
            raise ValueError("Missing url parameter")

        if not (url.startswith("http://") or url.startswith("https://")):
            url = f"https://{url}"

        parsed = urlparse(url)
        headers = self._build_proxy_headers(parsed.netloc, incoming_referer, incoming_headers)

        # Check if Range header is present
        range_header = None
        if incoming_headers:
            for key, value in incoming_headers.items():
                if key.lower() == "range" and value:
                    range_header = value
                    break

        resp = cffi_requests.get(
            url,
            headers=headers,
            timeout=self.timeout_seconds,
            impersonate=self.impersonate,
        )

        content = resp.content
        content_type = (resp.headers.get("Content-Type") or "").lower()
        
        # Check if content is m3u8
        is_m3u8 = "mpegurl" in content_type or "m3u8" in content_type or url.endswith(".m3u8")
        
        if is_m3u8:
            try:
                text = content.decode("utf-8", errors="replace")
                
                # Check if it's a valid m3u8 file
                if text.startswith("#EXTM3U"):
                    # Only rewrite valid m3u8 files
                    content = self._rewrite_m3u8(text, url).encode("utf-8")
                else:
                    # If not valid, check if it's a login page
                    if "登入" in text or "JavDB" in text:
                        # If it's a login page, return original content
                        pass
                    else:
                        # Try to find m3u8 content in case of proxy errors
                        import re
                        m3u8_match = re.search(r"#EXTM3U[\s\S]*", text)
                        if m3u8_match:
                            text = m3u8_match.group(0)
                            content = self._rewrite_m3u8(text, url).encode("utf-8")
            except Exception as e:
                # If m3u8 processing fails, return original content
                pass

        return ProxyContentResponse(
            status_code=resp.status_code,
            headers=self._filter_headers(resp.headers),
            content=content,
        )

    def _resolve_proxy2_url(self, method: str, query_string: str, body_url: str) -> str:
        if method.upper() == "POST":
            return body_url or ""

        raw_url = ""
        for param in query_string.split("&"):
            if param.startswith("url="):
                raw_url = param[4:]
                break

        if not raw_url:
            return ""

        try:
            return base64.b64decode(raw_url).decode("utf-8")
        except Exception:
            return unquote(raw_url)

    def _rewrite_m3u8(self, m3u8_content: str, base_url: str) -> str:
        # Keep behavior aligned with standalone av_player_server:
        # 1) rewrite EXT-X-KEY URI
        # 2) rewrite media segment lines
        from urllib.parse import urljoin

        def build_proxy2_url(raw_url: str) -> str:
            candidate = (raw_url or "").strip()
            if not candidate:
                return candidate

            lowered = candidate.lower()
            if (
                lowered.startswith("/proxy2?url=")
                or lowered.startswith(f"{self.proxy_base_path.lower()}/proxy2?url=")
                or lowered.startswith("/api/v1/video/proxy2?url=")
            ):
                return candidate

            absolute_url = candidate
            if not (candidate.startswith("http://") or candidate.startswith("https://")):
                absolute_url = urljoin(base_url, candidate)

            encoded_url = base64.b64encode(absolute_url.encode("utf-8")).decode("utf-8")
            return f"{self.proxy_base_path}/proxy2?url={encoded_url}"

        def replace_key_uri(match: re.Match) -> str:
            method = match.group(1)
            key_uri = match.group(2)
            proxy_key_url = build_proxy2_url(key_uri)
            return f'#EXT-X-KEY:METHOD={method},URI="{proxy_key_url}"'

        rewritten = _M3U8_KEY_PATTERN.sub(replace_key_uri, m3u8_content)

        lines = rewritten.split("\n")
        new_lines = []
        for line in lines:
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#"):
                new_lines.append(line)
                continue
            new_lines.append(build_proxy2_url(stripped_line))

        return "\n".join(new_lines)

    def _build_relative_proxy2_url(self, target_url: str) -> str:
        encoded = base64.b64encode(target_url.encode("utf-8")).decode("utf-8")
        return f"/proxy2?url={encoded}"

    def _build_absolute_proxy2_url(self, target_url: str) -> str:
        encoded = base64.b64encode(target_url.encode("utf-8")).decode("utf-8")
        return f"{self.proxy_base_path}/proxy2?url={encoded}"

    def _build_proxy_headers(self, netloc_or_domain: str, incoming_referer: str, incoming_headers: Dict[str, str] = None) -> Dict[str, str]:
        referer = incoming_referer or ""
        origin = ""
        lowered = (netloc_or_domain or "").lower()

        if "jable" in lowered or "javbus" in lowered:
            referer = f"https://{netloc_or_domain}/"
        elif "missav" in lowered or "surrit" in lowered or "mushroom" in lowered:
            referer = "https://missav.ai/"
            origin = "https://missav.ai"

        headers = {**_PROXY_HEADERS, "Referer": referer}
        if origin:
            headers["Origin"] = origin
        
        # Add JavDB cookies if needed
        if ("javdb" in lowered or "jdbstatic.com" in lowered) and self.javdb_cookie_header:
            headers["Cookie"] = self.javdb_cookie_header
        
        # Merge incoming headers if provided
        if incoming_headers:
            for key, value in incoming_headers.items():
                if key.lower() not in _EXCLUDED_HEADERS and value:
                    headers[key] = value
        
        return headers

    @staticmethod
    def _filter_headers(headers: Dict[str, str]) -> List[Tuple[str, str]]:
        return [(name, value) for name, value in headers.items() if name.lower() not in _EXCLUDED_HEADERS]
