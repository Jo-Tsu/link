from __future__ import annotations

from smallink.providers.trae_provider import TraeProvider, _parse_tool_calls_from_text


TOOLS = [
    {"type": "function", "function": {"name": "todo_write", "parameters": {}}},
    {"type": "function", "function": {"name": "grep", "parameters": {}}},
]


def test_parse_nested_tool_calls_with_narration() -> None:
    text = (
        "I will inspect the project first.\n\n"
        '{"tool_calls": ['
        '{"name": "todo_write", "arguments": {"todos": ['
        '{"content": "Inspect", "status": "in_progress"},'
        '{"content": "Verify", "status": "pending"}]}},'
        '{"name": "grep", "arguments": {"pattern": "session", "path": "smallink"}}'
        "]}"
    )

    calls, narration = _parse_tool_calls_from_text(text, TOOLS)

    assert [call.name for call in calls] == ["todo_write", "grep"]
    assert calls[0].arguments["todos"][1]["content"] == "Verify"
    assert narration == "I will inspect the project first."


def test_parse_rejects_tools_not_offered_to_the_model() -> None:
    calls, text = _parse_tool_calls_from_text(
        '{"tool_calls": [{"name": "delete_everything", "arguments": {}}]}', TOOLS
    )

    assert calls == []
    assert "delete_everything" in (text or "")


def test_stream_hides_tool_json_and_returns_structured_calls(monkeypatch) -> None:
    provider = TraeProvider()
    response = (
        "Checking the code now.\n"
        '```json\n{"tool_calls": [{"name": "grep", "arguments": '
        '{"pattern": "project", "path": "smallink"}}]}\n```'
    )
    monkeypatch.setattr(
        provider,
        "_exec",
        lambda prompt, model: iter(
            [{"type": "item.completed", "item": {"type": "agent_message", "text": response}}]
        ),
    )

    chunks = list(provider.stream(model="test", messages=[], tools=TOOLS))
    visible = "".join(chunk.text_delta or "" for chunk in chunks)
    turn = chunks[-1].turn

    assert visible == "Checking the code now."
    assert "tool_calls" not in visible
    assert turn is not None
    assert turn.text == "Checking the code now."
    assert [call.name for call in turn.tool_calls] == ["grep"]
    assert turn.finish_reason == "tool_calls"
