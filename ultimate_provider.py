from __future__ import annotations

import os
import sys
from typing import Any, Dict


CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
THIRD_PARTY_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
BACKEND_ROOT = os.path.abspath(os.path.join(THIRD_PARTY_ROOT, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from protocol.base import ProtocolProvider
from protocol.runtime_config import ProtocolConfigStore
from missav.client import MissavClient


def _parse_cookie_string(cookie_string: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in str(cookie_string or "").strip().split(";"):
        pair = part.strip()
        if not pair or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            cookies[key] = value
    return cookies


class MissavProvider(ProtocolProvider):
    @staticmethod
    def _normalize_domains(domains: Any) -> list:
        if isinstance(domains, str):
            raw_items = domains.replace("\n", ",").split(",")
        elif isinstance(domains, list):
            raw_items = domains
        else:
            raw_items = ["missav.ai", "missav.ws", "missav.com"]

        normalized = []
        for raw_item in raw_items:
            item = str(raw_item or "").strip().lower()
            item = item.removeprefix("https://").removeprefix("http://").strip("/")
            if item and item not in normalized:
                normalized.append(item)
        return normalized or ["missav.ai", "missav.ws", "missav.com"]

    @staticmethod
    def _build_cookie_header(cookies: Dict[str, Any]) -> str:
        if not isinstance(cookies, dict):
            return ""
        pairs = []
        for raw_key, raw_value in cookies.items():
            key = str(raw_key or "").strip()
            value = str(raw_value or "").strip()
            if key and value:
                pairs.append(f"{key}={value}")
        return "; ".join(pairs)

    def _get_javdb_cookie_header(self) -> str:
        config = ProtocolConfigStore().get_plugin_config("javdb", reload=True)
        return self._build_cookie_header((config or {}).get("cookies") or {})

    def normalize_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = dict(payload or {})
        config.setdefault("enabled", True)
        config.setdefault("impersonate", "chrome131")
        config["domains"] = self._normalize_domains(config.get("domains"))
        cookie_string = config.pop("cookie_string", None)
        if cookie_string is not None:
            config["cookies"] = _parse_cookie_string(cookie_string)
        elif isinstance(config.get("cookies"), str):
            config["cookies"] = _parse_cookie_string(config.get("cookies"))
        config.setdefault("cookies", {})
        return config

    def serialize_public_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        public_config = dict(self.normalize_config(config))
        if isinstance(public_config.get("cookies"), dict):
            public_config["cookie_string"] = "; ".join(
                f"{key}={value}"
                for key, value in public_config["cookies"].items()
                if str(key or "").strip() and str(value or "").strip()
            )
            public_config["cookies"] = {
                key: "***" if str(value or "").strip() else ""
                for key, value in public_config["cookies"].items()
            }
        else:
            public_config["cookie_string"] = ""
        return public_config

    def _get_client(self, config: Dict[str, Any] = None, proxy_base_path: str = "/api/v1/video") -> MissavClient:
        runtime_config = self.normalize_config(config)
        normalized_proxy_base_path = str(proxy_base_path or "/api/v1/video").strip() or "/api/v1/video"
        return MissavClient(
            proxy_base_path=normalized_proxy_base_path,
            impersonate=str(runtime_config.get("impersonate") or "chrome131").strip() or "chrome131",
            javdb_cookie_header=self._get_javdb_cookie_header(),
            missav_cookie_header=self._build_cookie_header(runtime_config.get("cookies") or {}),
            missav_domains=list(runtime_config.get("domains") or []),
        )

    def execute(self, capability: str, params: Dict[str, Any], context: Dict[str, Any], config: Dict[str, Any]):
        proxy_base_path = str(params.get("proxy_base_path") or "/api/v1/video").strip() or "/api/v1/video"
        client = self._get_client(config, proxy_base_path=proxy_base_path)
        if capability == "playback.sources.build":
            return client.build_sources(str(params.get("code") or ""))
        if capability == "playback.proxy.stream":
            return client.proxy_stream(
                domain=str(params.get("domain") or ""),
                path=str(params.get("path") or ""),
                query_string=str(params.get("query_string") or ""),
                incoming_referer=str(params.get("incoming_referer") or ""),
            )
        if capability == "playback.proxy.url":
            return client.proxy_url(
                method=str(params.get("method") or "GET"),
                query_string=str(params.get("query_string") or ""),
                body_url=str(params.get("body_url") or ""),
                incoming_referer=str(params.get("incoming_referer") or ""),
                incoming_headers=dict(params.get("incoming_headers") or {}),
            )
        if capability == "transport.http.request":
            return client._request(
                str(params.get("method") or "GET"),
                str(params.get("url") or ""),
                headers=dict(params.get("headers") or {}),
                stream=bool(params.get("stream", False)),
                timeout=int(params.get("timeout", 0) or 0) or None,
                allow_redirects=bool(params.get("allow_redirects", True)),
                impersonate=str(params.get("impersonate") or getattr(client, "impersonate", "chrome131")),
            )
        raise ValueError(f"unsupported capability: {capability}")
