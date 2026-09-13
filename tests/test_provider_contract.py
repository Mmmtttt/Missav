from __future__ import annotations

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
