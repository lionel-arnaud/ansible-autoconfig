"""OpenCode V2 transport and deployment regression tests."""
from __future__ import annotations

from trading_agent.reasoning import _extract_text, _request_v2_reply


class Response:
    def __init__(self, body=None):
        self.body = body or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class V2HTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None):
        self.calls.append(("post", url, json))
        if url.endswith("/api/session"):
            return Response({"data": {"id": "ses_test"}})
        return Response()

    def get(self, url):
        self.calls.append(("get", url, None))
        return Response({"data": [
            {"type": "user", "content": [{"type": "text", "text": "ignored"}]},
            {"type": "assistant", "content": [
                {"type": "reasoning", "text": "hidden"},
                {"type": "text", "text": "final answer"},
            ]},
        ]})

    def delete(self, url):
        self.calls.append(("delete", url, None))
        return Response()


def test_v2_transport_waits_for_final_answer_and_removes_session():
    http = V2HTTP()

    assert _request_v2_reply(http, "https://ai.example", "decide") == "final answer"
    assert http.calls == [
        ("post", "https://ai.example/api/session", {"title": "trading-agent cycle"}),
        ("post", "https://ai.example/api/session/ses_test/prompt", {"text": "decide"}),
        ("post", "https://ai.example/api/experimental/session/ses_test/wait", None),
        ("get", "https://ai.example/api/session/ses_test/message", None),
        ("delete", "https://ai.example/api/session/ses_test", None),
    ]


def test_v2_extract_text_uses_the_latest_assistant_message():
    assert _extract_text({"data": [
        {"type": "assistant", "content": [{"type": "text", "text": "old"}]},
        {"type": "assistant", "content": [{"type": "text", "text": "new"}]},
    ]}) == "new"
