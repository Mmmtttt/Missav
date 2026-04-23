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
from missav.client import MissavClient


class MissavProvider(ProtocolProvider):
    def _get_client(self, proxy_base_path: str = "/api/v1/video") -> MissavClient:
        normalized_proxy_base_path = str(proxy_base_path or "/api/v1/video").strip() or "/api/v1/video"
        return MissavClient(proxy_base_path=normalized_proxy_base_path)

    def execute(self, capability: str, params: Dict[str, Any], context: Dict[str, Any], config: Dict[str, Any]):
        proxy_base_path = str(params.get("proxy_base_path") or "/api/v1/video").strip() or "/api/v1/video"
        client = self._get_client(proxy_base_path=proxy_base_path)
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
                impersonate=str(params.get("impersonate") or getattr(client, "impersonate", "chrome120")),
            )
        raise ValueError(f"unsupported capability: {capability}")
