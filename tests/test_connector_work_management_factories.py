from __future__ import annotations

import inspect
from typing import Any, Callable

from smallink.connectors.tool_utils import request
from smallink.connectors.tools_domain.work_management import (
    make_asana_tools,
    make_clickup_tools,
    make_confluence_tools,
    make_gitlab_tools,
    make_jira_tools,
    make_linear_tools,
    make_work_management_tools,
)


class _FakeSecrets:
    def __init__(self, profiles: dict[str, dict[str, Any]] | None = None) -> None:
        self.profiles = dict(profiles or {})

    def get(self, key: str) -> dict[str, Any] | None:
        value = self.profiles.get(key)
        return dict(value) if value is not None else None


def _tools_by_name(tools: list[Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    return {tool.__name__: tool for tool in tools}


def _tool_schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_FACTORY_NAMES = (
    (
        make_jira_tools,
        ["jira_search_issues", "jira_get_issue", "jira_create_issue"],
    ),
    (
        make_confluence_tools,
        [
            "confluence_search",
            "confluence_get_page",
            "confluence_create_page",
        ],
    ),
    (
        make_linear_tools,
        [
            "linear_search_issues",
            "linear_get_issue",
            "linear_list_teams",
            "linear_create_issue",
        ],
    ),
    (
        make_gitlab_tools,
        [
            "gitlab_search",
            "gitlab_get_issue",
            "gitlab_get_merge_request",
            "gitlab_create_issue",
        ],
    ),
    (
        make_asana_tools,
        [
            "asana_list_workspaces",
            "asana_search_tasks",
            "asana_get_task",
            "asana_create_task",
        ],
    ),
    (
        make_clickup_tools,
        [
            "clickup_list_teams",
            "clickup_list_spaces",
            "clickup_list_lists",
            "clickup_list_tasks",
            "clickup_get_task",
            "clickup_create_task",
            "clickup_update_task",
            "clickup_add_comment",
        ],
    ),
)


_CONTRACTS: dict[
    str, tuple[str, dict[str, Any], list[str], list[str], bool]
] = {
    "jira_search_issues": (
        "Search Jira issues using JQL.",
        {"jql": {"type": "string"}, "max_results": {"type": "integer"}},
        ["jql"],
        ["jira", "read"],
        False,
    ),
    "jira_get_issue": (
        "Read a Jira issue.",
        {"issue_key": {"type": "string"}},
        ["issue_key"],
        ["jira", "read"],
        False,
    ),
    "jira_create_issue": (
        "Create a Jira issue. Requires user approval.",
        {
            "project_key": {"type": "string"},
            "issue_type": {"type": "string"},
            "summary": {"type": "string"},
            "description": {"type": "string"},
        },
        ["project_key", "issue_type", "summary"],
        ["jira", "write"],
        True,
    ),
    "confluence_search": (
        "Search Confluence pages.",
        {"query": {"type": "string"}, "max_results": {"type": "integer"}},
        ["query"],
        ["confluence", "read"],
        False,
    ),
    "confluence_get_page": (
        "Read a Confluence page.",
        {"page_id": {"type": "string"}},
        ["page_id"],
        ["confluence", "read"],
        False,
    ),
    "confluence_create_page": (
        "Create a Confluence page. Body should be Confluence storage-format HTML. "
        "Requires user approval.",
        {
            "space_key": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "parent_id": {"type": "string"},
        },
        ["space_key", "title", "body"],
        ["confluence", "write"],
        True,
    ),
    "linear_search_issues": (
        "Search Linear issues by text.",
        {"query": {"type": "string"}, "max_results": {"type": "integer"}},
        ["query"],
        ["linear", "read"],
        False,
    ),
    "linear_get_issue": (
        "Read a Linear issue (with comments) by ID or key like ENG-123.",
        {"issue_id": {"type": "string"}},
        ["issue_id"],
        ["linear", "read"],
        False,
    ),
    "linear_list_teams": (
        "List Linear teams (IDs are needed to create issues).",
        {},
        [],
        ["linear", "read"],
        False,
    ),
    "linear_create_issue": (
        "Create a Linear issue. Get team_id from linear_list_teams. Requires user "
        "approval.",
        {
            "team_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
        },
        ["team_id", "title"],
        ["linear", "write"],
        True,
    ),
    "gitlab_search": (
        "Search GitLab projects, issues, or merge_requests (scope).",
        {
            "query": {"type": "string"},
            "scope": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        ["query"],
        ["gitlab", "read"],
        False,
    ),
    "gitlab_get_issue": (
        "Read a GitLab issue. project is an ID or full path like group/repo.",
        {"project": {"type": "string"}, "issue_iid": {"type": "integer"}},
        ["project", "issue_iid"],
        ["gitlab", "read"],
        False,
    ),
    "gitlab_get_merge_request": (
        "Read a GitLab merge request. project is an ID or full path like group/repo.",
        {"project": {"type": "string"}, "mr_iid": {"type": "integer"}},
        ["project", "mr_iid"],
        ["gitlab", "read"],
        False,
    ),
    "gitlab_create_issue": (
        "Create a GitLab issue. Requires user approval.",
        {
            "project": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
        },
        ["project", "title"],
        ["gitlab", "write"],
        True,
    ),
    "asana_list_workspaces": (
        "List Asana workspaces (GIDs are needed to search tasks).",
        {},
        [],
        ["asana", "read"],
        False,
    ),
    "asana_search_tasks": (
        "Search Asana tasks by name in a workspace. Get workspace_gid from "
        "asana_list_workspaces.",
        {
            "workspace_gid": {"type": "string"},
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        ["workspace_gid", "query"],
        ["asana", "read"],
        False,
    ),
    "asana_get_task": (
        "Read an Asana task.",
        {"task_gid": {"type": "string"}},
        ["task_gid"],
        ["asana", "read"],
        False,
    ),
    "asana_create_task": (
        "Create an Asana task in a project. Requires user approval.",
        {
            "project_gid": {"type": "string"},
            "name": {"type": "string"},
            "notes": {"type": "string"},
        },
        ["project_gid", "name"],
        ["asana", "write"],
        True,
    ),
    "clickup_list_teams": (
        "List ClickUp workspaces (team ids are needed to browse spaces).",
        {},
        [],
        ["clickup", "read"],
        False,
    ),
    "clickup_list_spaces": (
        "List spaces in a ClickUp workspace.",
        {"team_id": {"type": "string"}},
        ["team_id"],
        ["clickup", "read"],
        False,
    ),
    "clickup_list_lists": (
        "List folderless lists in a ClickUp space (list ids hold the tasks).",
        {"space_id": {"type": "string"}},
        ["space_id"],
        ["clickup", "read"],
        False,
    ),
    "clickup_list_tasks": (
        "List tasks in a ClickUp list.",
        {
            "list_id": {"type": "string"},
            "include_closed": {"type": "boolean"},
            "max_results": {"type": "integer"},
        },
        ["list_id"],
        ["clickup", "read"],
        False,
    ),
    "clickup_get_task": (
        "Read a ClickUp task (with subtasks) by id.",
        {"task_id": {"type": "string"}},
        ["task_id"],
        ["clickup", "read"],
        False,
    ),
    "clickup_create_task": (
        "Create a ClickUp task in a list. Requires user approval.",
        {
            "list_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
        },
        ["list_id", "name"],
        ["clickup", "write"],
        True,
    ),
    "clickup_update_task": (
        "Update a ClickUp task's name, description, or status. Requires user approval.",
        {
            "task_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
        },
        ["task_id"],
        ["clickup", "write"],
        True,
    ),
    "clickup_add_comment": (
        "Comment on a ClickUp task. Requires user approval.",
        {"task_id": {"type": "string"}, "text": {"type": "string"}},
        ["task_id", "text"],
        ["clickup", "write"],
        True,
    ),
}


def test_factories_preserve_order_signatures_schemas_and_metadata() -> None:
    secrets = _FakeSecrets()
    expected_all_names = [name for _, names in _FACTORY_NAMES for name in names]

    factories = (*_FACTORY_NAMES, (make_work_management_tools, expected_all_names))
    for factory, expected_names in factories:
        signature = inspect.signature(factory)
        assert list(signature.parameters) == ["secrets", "roots", "request_fn"]
        assert signature.parameters["roots"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["request_fn"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["roots"].default is None
        assert signature.parameters["request_fn"].default is request
        assert [tool.__name__ for tool in factory(secrets)] == expected_names

    tools = make_work_management_tools(secrets)
    assert set(_CONTRACTS) == set(expected_all_names)
    for tool in tools:
        description, properties, required, capabilities, approval = _CONTRACTS[
            tool.__name__
        ]
        assert tool.__link_schema__ == _tool_schema(
            tool.__name__, description, properties, required
        )
        assert tool.__doc__ == description

        metadata = tool.__aisuite_tool_metadata__
        assert metadata.name == tool.__name__
        assert metadata.category == "connector"
        assert metadata.capabilities == capabilities
        assert metadata.requires_approval is approval
        assert metadata.risk_level == ("medium" if approval else "low")


def test_factories_route_all_work_management_http_through_injected_request() -> None:
    secrets = _FakeSecrets(
        {
            "jira:default": {
                "base_url": "https://jira.example/",
                "email": "jira@example.com",
                "api_token": "jira-token",
            },
            "confluence:default": {
                "base_url": "https://wiki.example/",
                "email": "wiki@example.com",
                "api_token": "wiki-token",
            },
            "linear:default": {"api_key": "lin_api_x"},
            "gitlab:default": {
                "token": "glpat-x",
                "base_url": "https://gitlab.example/",
            },
            "asana:default": {"token": "asana-token"},
            "clickup:default": {"api_token": "clickup-token"},
        }
    )
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        call = {"method": method, "url": url, **kwargs}
        calls.append(call)
        return {"ok": True, "data": {"call": len(calls)}}

    tools = _tools_by_name(
        make_work_management_tools(secrets, roots=[object()], request_fn=fake_request)
    )

    assert tools["jira_search_issues"]("project = TEST", 99)["ok"] is True
    assert calls[-1] == {
        "method": "GET",
        "url": "https://jira.example/rest/api/3/search",
        "auth": ("jira@example.com", "jira-token"),
        "params": {"jql": "project = TEST", "maxResults": 20},
    }

    tools["jira_create_issue"]("OPS", "Task", "Investigate")
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["url"] == "https://jira.example/rest/api/3/issue"
    assert calls[-1]["json"]["fields"]["description"]["content"][0][
        "content"
    ][0]["text"] == "Investigate"

    tools["confluence_get_page"]("page-1")
    assert calls[-1] == {
        "method": "GET",
        "url": "https://wiki.example/wiki/rest/api/content/page-1",
        "auth": ("wiki@example.com", "wiki-token"),
        "params": {"expand": "body.storage,version,space"},
    }

    tools["linear_search_issues"]("crash", max_results=0)
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["url"] == "https://api.linear.app/graphql"
    assert calls[-1]["headers"] == {
        "Authorization": "lin_api_x",
        "Content-Type": "application/json",
    }
    assert calls[-1]["json"]["variables"] == {"term": "crash", "first": 10}

    tools["gitlab_get_issue"]("group/repo", 7)
    assert calls[-1] == {
        "method": "GET",
        "url": "https://gitlab.example/api/v4/projects/group%2Frepo/issues/7",
        "headers": {"PRIVATE-TOKEN": "glpat-x"},
    }

    tools["asana_search_tasks"]("workspace-1", "report", max_results=99)
    assert calls[-1] == {
        "method": "GET",
        "url": "https://app.asana.com/api/1.0/workspaces/workspace-1/typeahead",
        "headers": {
            "Authorization": "Bearer asana-token",
            "Accept": "application/json",
        },
        "params": {
            "resource_type": "task",
            "query": "report",
            "count": 20,
        },
    }

    tools["clickup_list_tasks"]("list 1", include_closed=True, max_results=2)
    assert calls[-1] == {
        "method": "GET",
        "url": "https://api.clickup.com/api/v2/list/list%201/task",
        "headers": {"Authorization": "clickup-token"},
        "params": {"include_closed": "true", "page": 0},
    }

    before = len(calls)
    assert tools["clickup_update_task"]("task-1") == {
        "error": "nothing to update: pass name, description, or status"
    }
    assert len(calls) == before

    tools["clickup_update_task"]("task 1", name="New name", status="done")
    assert calls[-1] == {
        "method": "PUT",
        "url": "https://api.clickup.com/api/v2/task/task%201",
        "headers": {"Authorization": "clickup-token"},
        "json": {"name": "New name", "status": "done"},
    }


def test_factories_return_profile_errors_without_making_requests() -> None:
    def unexpected_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("request should not be called for missing profiles")

    tools = _tools_by_name(
        make_work_management_tools(_FakeSecrets(), request_fn=unexpected_request)
    )
    for name, arguments in (
        ("jira_get_issue", ("OPS-1",)),
        ("confluence_get_page", ("page-1",)),
        ("linear_get_issue", ("ENG-1",)),
        ("gitlab_get_issue", ("group/repo", 1)),
        ("asana_get_task", ("task-1",)),
        ("clickup_get_task", ("task-1",)),
    ):
        assert "not connected" in tools[name](*arguments)["error"]
