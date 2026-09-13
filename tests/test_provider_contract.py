from __future__ import annotations

import ultimate_provider as provider_module
from ultimate_provider import MissavProvider


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def build_sources(self, code):
        return [{"code": code}]


def test_normalize_config_parses_domains_and_cookie_string():
    config = MissavProvider().normalize_config(
        {
            "domains": "https://missav.ai, missav.ws/",
            "cookie_string": "session=abc; theme=dark",
        }
    )

    assert config["domains"] == ["missav.ai", "missav.ws"]
    assert config["cookies"] == {"session": "abc", "theme": "dark"}
    assert config["impersonate"] == "chrome131"


def test_execute_maps_playback_sources_and_passes_normalized_config(monkeypatch):
    provider = MissavProvider()
    created = []

    def fake_client(**kwargs):
        created.append(kwargs)
        return FakeClient(**kwargs)

    monkeypatch.setattr("ultimate_provider.MissavClient", fake_client)
    result = provider.execute(
        "playback.sources.build",
        {"code": "ABC-001"},
        {},
        {"domains": "missav.ai", "cookie_string": "session=abc"},
    )

    assert result == [{"code": "ABC-001"}]
    assert created[0]["missav_domains"] == ["missav.ai"]
    assert created[0]["missav_cookie_header"] == "session=abc"


def test_execute_maps_proxy_stream_and_url_capabilities(monkeypatch):
    provider = MissavProvider()
    calls = []

    class Client(FakeClient):
        def proxy_stream(self, **kwargs):
            calls.append(("stream", kwargs))
            return "stream-result"

        def proxy_url(self, **kwargs):
            calls.append(("url", kwargs))
            return "url-result"

    monkeypatch.setattr(provider_module, "MissavClient", lambda **kwargs: Client(**kwargs))

    stream = provider.execute("playback.proxy.stream", {"domain": "media.example", "path": "/index.m3u8", "query_string": "x=1"}, {}, {})
    url = provider.execute("playback.proxy.url", {"method": "GET", "query_string": "url=encoded"}, {}, {})

    assert stream == "stream-result"
    assert url == "url-result"
    assert calls == [
        ("stream", {"domain": "media.example", "path": "/index.m3u8", "query_string": "x=1", "incoming_referer": ""}),
        ("url", {"method": "GET", "query_string": "url=encoded", "body_url": "", "incoming_referer": "", "incoming_headers": {}}),
    ]


def test_execute_transport_request_forwards_stream_and_timeout(monkeypatch):
    provider = MissavProvider()
    calls = []

    class Client(FakeClient):
        impersonate = "fixture-browser"

        def _request(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "transport-result"

    monkeypatch.setattr(provider_module, "MissavClient", lambda **kwargs: Client(**kwargs))

    result = provider.execute(
        "transport.http.request",
        {"method": "POST", "url": "https://example.test/api", "headers": {"X-Test": "1"}, "stream": True, "timeout": 9, "allow_redirects": False},
        {},
        {},
    )

    assert result == "transport-result"
    assert calls == [
        (("POST", "https://example.test/api"), {"headers": {"X-Test": "1"}, "stream": True, "timeout": 9, "allow_redirects": False, "impersonate": "fixture-browser"})
    ]


def test_execute_rejects_unknown_capability(monkeypatch):
    provider = MissavProvider()
    monkeypatch.setattr(provider_module, "MissavClient", lambda **kwargs: FakeClient(**kwargs))

    try:
        provider.execute("unsupported.capability", {}, {}, {})
    except ValueError as exc:
        assert "unsupported capability" in str(exc)
    else:
        raise AssertionError("unknown capability must be rejected")
