"""GitHub host resolution for the Copilot device flow.

The flow was hardcoded to github.com, which strands two populations:
GitHub Enterprise Server / ghe.com deployments (different OAuth
endpoints entirely), and enterprise-managed accounts on github.com whose
IdP isn't offered by the generic sign-in page.
"""

from __future__ import annotations

import pytest

from switchbay.llmgateway import base, github_copilot as gc


@pytest.mark.parametrize(("raw", "want"), [
    (None, "github.com"),
    ("", "github.com"),
    ("github.com", "github.com"),
    ("  GitHub.com  ", "github.com"),
    ("acme.ghe.com", "acme.ghe.com"),
    ("https://acme.ghe.com", "acme.ghe.com"),
    ("https://github.example.com/", "github.example.com"),
    ("http://ghes.internal/path/ignored", "ghes.internal"),
    # EMU: path is stripped for host but slug is preserved separately.
    ("https://github.com/enterprises/acme/sso", "github.com"),
    ("www.github.com/enterprises/acme", "github.com"),
])
def test_host_normalisation(raw, want):
    assert gc._normalize_host(raw) == want


@pytest.mark.parametrize(("raw", "host", "slug"), [
    ("https://github.com/enterprises/acme/sso", "github.com", "acme"),
    ("github.com/enterprises/my-org", "github.com", "my-org"),
    ("www.github.com/enterprises/Foo", "github.com", "Foo"),
    ("acme.ghe.com", "acme.ghe.com", None),
    ("", "github.com", None),
])
def test_parse_github_host_input_emu_slug(raw, host, slug):
    h, s = gc.parse_github_host_input(raw)
    assert h == host
    assert s == slug


def test_endpoints_include_sso_uri_for_emu_slug():
    eps = gc._endpoints("github.com", sso_slug="acme")
    assert eps["host"] == "github.com"
    assert eps["sso_uri"] == "https://github.com/enterprises/acme/sso"
    assert "acme" in eps["sso_hint"]


def test_supports_chat_completions_prefers_model_picker_enabled():
    assert gc._supports_chat_completions({
        "id": "gpt-4o", "model_picker_enabled": True,
    })
    assert not gc._supports_chat_completions({
        "id": "hidden", "model_picker_enabled": False,
    })
    assert not gc._supports_chat_completions({
        "id": "resp-only",
        "capabilities": {"supported_endpoints": ["/responses"]},
    })
    assert gc._supports_chat_completions({
        "id": "chatty",
        "capabilities": {
            "supported_endpoints": ["/chat/completions", "/responses"],
        },
    })


def test_picker_includes_responses_only_chat_models():
    """Newer Copilot rows refuse /chat/completions; they still belong
    in the picker and ride /responses."""
    codex = {
        "id": "gpt-5.4-codex",
        "model_picker_enabled": True,
        "supported_endpoints": ["/responses"],
        "capabilities": {"type": "chat", "supports": {"tool_calls": True}},
    }
    assert gc._is_picker_model(codex)
    assert not gc._supports_chat_completions(codex)
    assert not gc._is_picker_model({
        "id": "no-tools",
        "model_picker_enabled": True,
        "supported_endpoints": ["/chat/completions"],
        "capabilities": {"type": "chat", "supports": {"tool_calls": False}},
    })
    both = {
        "id": "gpt-5.4",
        "model_picker_enabled": True,
        "supported_endpoints": ["/chat/completions", "/responses"],
        "capabilities": {"type": "chat", "supports": {"tool_calls": True}},
    }
    assert gc._is_picker_model(both)
    assert gc._supports_chat_completions(both)
    assert not gc._is_picker_model({
        "id": "embed",
        "model_picker_enabled": True,
        "capabilities": {"type": "embeddings"},
    })


def test_catalog_routes_responses_only_and_prefers_chat_when_both():
    gc._model_endpoints.clear()
    gc._learned_kind.clear()
    ids = gc._ingest_catalog([
        {
            "id": "gpt-5.4-codex",
            "model_picker_enabled": True,
            "supported_endpoints": ["/responses"],
            "capabilities": {"type": "chat", "supports": {"tool_calls": True}},
        },
        {
            "id": "gpt-5.4",
            "model_picker_enabled": True,
            "supported_endpoints": ["/chat/completions", "/responses"],
            "capabilities": {"type": "chat", "supports": {"tool_calls": True}},
        },
        {
            "id": "hidden",
            "model_picker_enabled": False,
            "supported_endpoints": ["/chat/completions"],
        },
    ])
    assert ids == ["gpt-5.4", "gpt-5.4-codex"]
    assert gc._preferred_kind("gpt-5.4") == "chat"
    assert gc._preferred_kind("gpt-5.4-codex") == "responses"
    assert gc._endpoint_order("gpt-5.4") == ("chat", "responses")
    assert gc._endpoint_order("gpt-5.4-codex") == ("responses", "chat")
    # Unknown id: try chat first, then responses.
    assert gc._endpoint_order("mystery-future") == ("chat", "responses")
    gc._learn_kind("mystery-future", "responses")
    assert gc._preferred_kind("mystery-future") == "responses"
    gc._model_endpoints.clear()
    gc._learned_kind.clear()


def test_wrong_endpoint_error_detects_copilot_400():
    assert gc._is_wrong_endpoint_error(
        '{"error":{"code":"unsupported_api_for_model",'
        '"message":"Model not accessible via the /chat/completions endpoint"}}'
    )
    assert gc._is_wrong_endpoint_error(
        "This model does not support /chat/completions; use the Responses API"
    )
    assert not gc._is_wrong_endpoint_error(
        '{"error":{"message":"invalid tool schema"}}'
    )


class _FakeSse:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._i]
        self._i += 1
        return (line + "\n").encode("utf-8")


class _FakeResp:
    def __init__(self, status: int, text: str = "", lines: list[str] | None = None):
        self.status = status
        self._text = text
        self.content = _FakeSse(lines or [])

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch, posts: list[_FakeResp], urls: list[str]):
    queue = list(posts)

    class _FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            urls.append(url)
            return queue.pop(0)

    async def _fake_bearer():
        return "tok"

    monkeypatch.setattr(gc, "_bearer", _fake_bearer)
    monkeypatch.setattr(gc.aiohttp, "ClientSession", _FakeSession)


@pytest.mark.asyncio
async def test_chat_stream_retries_responses_after_chat_400(monkeypatch):
    gc._model_endpoints.clear()
    gc._learned_kind.clear()
    urls: list[str] = []
    _patch_session(monkeypatch, [
        _FakeResp(400, text=(
            '{"error":{"code":"unsupported_api_for_model",'
            '"message":"not accessible via the /chat/completions endpoint"}}'
        )),
        _FakeResp(200, lines=[
            'data: {"type":"response.output_text.delta","delta":"hi"}',
            'data: {"type":"response.completed","response":{"usage":{"input_tokens":1,"output_tokens":1}}}',
        ]),
    ], urls)
    events = []
    async for ev in gc.chat_stream(base.ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-5.4-codex",
    )):
        events.append(ev)
    assert urls[0].endswith("/chat/completions")
    assert urls[1].endswith("/responses")
    assert [e.text for e in events if isinstance(e, base.TextChunk)] == ["hi"]
    assert gc._preferred_kind("gpt-5.4-codex") == "responses"
    gc._model_endpoints.clear()
    gc._learned_kind.clear()


@pytest.mark.asyncio
async def test_chat_stream_posts_responses_when_catalog_says_so(monkeypatch):
    gc._ingest_catalog([{
        "id": "gpt-5.4-codex",
        "model_picker_enabled": True,
        "supported_endpoints": ["/responses"],
        "capabilities": {"type": "chat", "supports": {"tool_calls": True}},
    }])
    urls: list[str] = []
    _patch_session(monkeypatch, [
        _FakeResp(200, lines=[
            'data: {"type":"response.output_text.delta","delta":"ok"}',
            'data: {"type":"response.completed","response":{}}',
        ]),
    ], urls)
    events = []
    async for ev in gc.chat_stream(base.ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-5.4-codex",
    )):
        events.append(ev)
    assert len(urls) == 1
    assert urls[0].endswith("/responses")
    assert [e.text for e in events if isinstance(e, base.TextChunk)] == ["ok"]
    gc._model_endpoints.clear()
    gc._learned_kind.clear()


def test_responses_body_uses_flat_tools_and_input_items():
    req = base.ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        system="be brief",
        model="gpt-5.4-codex",
        max_tokens=128,
        tools=[{
            "name": "search_wiki",
            "description": "find pages",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        }],
    )
    body = gc._build_responses_body(req, "gpt-5.4-codex")
    assert body["model"] == "gpt-5.4-codex"
    assert body["stream"] is True
    assert body["store"] is False
    assert body["instructions"] == "be brief"
    assert body["input"][0]["role"] == "user"
    assert body["max_output_tokens"] == 128
    assert "max_tokens" not in body
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["name"] == "search_wiki"
    assert "function" not in body["tools"][0]
    chat = gc._build_chat_body(req, "gpt-5.4")
    assert chat["max_completion_tokens"] == 128
    assert chat["tools"][0]["function"]["name"] == "search_wiki"


def test_editor_headers_match_current_vscode_chat():
    h = gc._editor_headers()
    assert h["Editor-Version"].startswith("vscode/1.")
    ver = h["Editor-Version"].split("/", 1)[-1]
    assert tuple(int(p) for p in ver.split(".")[:2]) >= (1, 137)
    assert h["Editor-Plugin-Version"].startswith("copilot-chat/")
    plugin = h["Editor-Plugin-Version"].split("/", 1)[-1]
    assert tuple(int(p) for p in plugin.split(".")[:2]) >= (0, 65)
    assert h["Copilot-Integration-Id"] == "vscode-chat"
    assert h["User-Agent"] == f"GitHubCopilotChat/{plugin}"
    assert "Openai-Intent" not in h
    assert "X-Initiator" not in h


def test_editor_headers_agent_intent_when_tools():
    user = gc._editor_headers(agent=False)
    assert user["X-Initiator"] == "user"
    assert user["Openai-Intent"] == "conversation-edits"
    agent = gc._editor_headers(agent=True)
    assert agent["X-Initiator"] == "agent"
    assert agent["Openai-Intent"] == "conversation-agent"
    assert agent["User-Agent"] == user["User-Agent"]


def test_static_model_suggestions_are_current_catalog():
    sugg = gc.PROVIDER["model_suggestions"]
    assert gc.DEFAULT_MODEL == "gpt-5.4"
    assert gc.DEFAULT_MODEL in sugg
    assert "gpt-4o" not in sugg
    assert "o3-mini" not in sugg
    families = {s.split("-", 1)[0] for s in sugg}
    # Cold-cache diversity: OpenAI, Anthropic, Google, xAI.
    assert "gpt" in families
    assert any(s.startswith("claude") for s in sugg)
    assert any(s.startswith("gemini") for s in sugg)
    assert any(s.startswith("grok") for s in sugg)
    # Retired / legacy ids stay out of the cold-cache list. Live
    # GET /models remains authoritative, including responses-only rows.
    assert "gpt-5-mini" not in sugg


def test_dotcom_endpoints_are_unchanged():
    eps = gc._endpoints("github.com")
    assert eps["device_code"] == "https://github.com/login/device/code"
    assert eps["access_token"] == "https://github.com/login/oauth/access_token"
    assert eps["copilot_token"] == "https://api.github.com/copilot_internal/v2/token"
    assert eps["api_base"] == "https://api.githubcopilot.com"


def test_ghe_com_endpoints_target_the_tenant():
    eps = gc._endpoints("acme.ghe.com")
    assert eps["device_code"] == "https://acme.ghe.com/login/device/code"
    assert eps["copilot_token"].startswith("https://api.acme.ghe.com/")
    assert "github.com" not in eps["device_code"]


def test_enterprise_server_endpoints_use_api_v3():
    eps = gc._endpoints("github.example.com")
    assert eps["device_code"] == "https://github.example.com/login/device/code"
    assert "/api/v3/" in eps["copilot_token"]


def test_access_denied_explains_the_sso_case():
    eps = gc._endpoints("github.com")
    msg = gc._auth_error_help("access_denied", eps)
    assert "Enterprise Managed User" in msg
    assert "sso" in msg.lower()


def test_unknown_errors_still_surface_verbatim():
    eps = gc._endpoints("github.com")
    assert "weird_thing" in gc._auth_error_help("weird_thing", eps)


def test_host_round_trips_through_secrets(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(gc.secrets, "set_key", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(gc.secrets, "delete_key", lambda k: store.pop(k, None))
    monkeypatch.setattr(gc.secrets, "get", lambda k: store.get(k))

    assert gc.set_host("acme.ghe.com") == "acme.ghe.com"
    assert gc.get_host() == "acme.ghe.com"
    # Back to the default clears the override rather than storing it.
    assert gc.set_host("github.com") == "github.com"
    assert gc._HOST_KEY not in store
    assert gc.get_host() == "github.com"
