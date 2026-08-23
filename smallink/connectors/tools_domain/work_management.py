"""Work-management connector tools."""

from __future__ import annotations

from typing import Any, Callable, Optional
from urllib.parse import quote

from ...secrets import SecretStore
from ..tool_utils import attach, bearer_headers, clamp, profile, request, schema


def _atlassian_base(connector_profile: dict[str, Any]) -> str:
    return str(connector_profile.get("base_url", "")).rstrip("/")


def _basic_auth(email: str, token: str) -> tuple[str, str]:
    return (email, token)


def _gitlab_api(connector_profile: dict[str, Any]) -> str:
    base = str(connector_profile.get("base_url") or "https://gitlab.com").rstrip(
        "/"
    )
    return f"{base}/api/v4"


def _linear_gql(
    request_fn: Callable[..., dict[str, Any]],
    api_key: str,
    query: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    return request_fn(
        "POST",
        "https://api.linear.app/graphql",
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        json={"query": query, "variables": variables},
    )


def make_jira_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Jira connector tools."""
    _ = roots
    tools: list[Callable[..., Any]] = []

    def jira_search_issues(jql: str, max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "jira", "base_url", "email", "api_token"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"{_atlassian_base(connector_profile)}/rest/api/3/search",
            auth=_basic_auth(
                connector_profile["email"], connector_profile["api_token"]
            ),
            params={
                "jql": jql,
                "maxResults": max(1, min(int(max_results or 10), 20)),
            },
        )

    jira_search_issues.__name__ = "jira_search_issues"
    tools.append(
        attach(
            jira_search_issues,
            schema(
                "jira_search_issues",
                "Search Jira issues using JQL.",
                {"jql": {"type": "string"}, "max_results": {"type": "integer"}},
                ["jql"],
            ),
            caps=["jira", "read"],
        )
    )

    def jira_get_issue(issue_key: str) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "jira", "base_url", "email", "api_token"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"{_atlassian_base(connector_profile)}/rest/api/3/issue/{issue_key}",
            auth=_basic_auth(
                connector_profile["email"], connector_profile["api_token"]
            ),
        )

    jira_get_issue.__name__ = "jira_get_issue"
    tools.append(
        attach(
            jira_get_issue,
            schema(
                "jira_get_issue",
                "Read a Jira issue.",
                {"issue_key": {"type": "string"}},
                ["issue_key"],
            ),
            caps=["jira", "read"],
        )
    )

    def jira_create_issue(
        project_key: str, issue_type: str, summary: str, description: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "jira", "base_url", "email", "api_token"
        )
        if err:
            return err
        payload = {
            "fields": {
                "project": {"key": project_key},
                "issuetype": {"name": issue_type},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": description or summary}
                            ],
                        }
                    ],
                },
            }
        }
        return request_fn(
            "POST",
            f"{_atlassian_base(connector_profile)}/rest/api/3/issue",
            auth=_basic_auth(
                connector_profile["email"], connector_profile["api_token"]
            ),
            json=payload,
        )

    jira_create_issue.__name__ = "jira_create_issue"
    tools.append(
        attach(
            jira_create_issue,
            schema(
                "jira_create_issue",
                "Create a Jira issue. Requires user approval.",
                {
                    "project_key": {"type": "string"},
                    "issue_type": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["project_key", "issue_type", "summary"],
            ),
            approval=True,
            caps=["jira", "write"],
        )
    )

    return tools


def make_confluence_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Confluence connector tools."""
    _ = roots
    tools: list[Callable[..., Any]] = []

    def confluence_search(query: str, max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "confluence", "base_url", "email", "api_token"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"{_atlassian_base(connector_profile)}/wiki/rest/api/search",
            auth=_basic_auth(
                connector_profile["email"], connector_profile["api_token"]
            ),
            params={
                "cql": f'text ~ "{query}"',
                "limit": max(1, min(int(max_results or 10), 20)),
            },
        )

    confluence_search.__name__ = "confluence_search"
    tools.append(
        attach(
            confluence_search,
            schema(
                "confluence_search",
                "Search Confluence pages.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["confluence", "read"],
        )
    )

    def confluence_get_page(page_id: str) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "confluence", "base_url", "email", "api_token"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"{_atlassian_base(connector_profile)}/wiki/rest/api/content/{page_id}",
            auth=_basic_auth(
                connector_profile["email"], connector_profile["api_token"]
            ),
            params={"expand": "body.storage,version,space"},
        )

    confluence_get_page.__name__ = "confluence_get_page"
    tools.append(
        attach(
            confluence_get_page,
            schema(
                "confluence_get_page",
                "Read a Confluence page.",
                {"page_id": {"type": "string"}},
                ["page_id"],
            ),
            caps=["confluence", "read"],
        )
    )

    def confluence_create_page(
        space_key: str, title: str, body: str, parent_id: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "confluence", "base_url", "email", "api_token"
        )
        if err:
            return err
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        return request_fn(
            "POST",
            f"{_atlassian_base(connector_profile)}/wiki/rest/api/content",
            auth=_basic_auth(
                connector_profile["email"], connector_profile["api_token"]
            ),
            json=payload,
        )

    confluence_create_page.__name__ = "confluence_create_page"
    tools.append(
        attach(
            confluence_create_page,
            schema(
                "confluence_create_page",
                "Create a Confluence page. Body should be Confluence storage-format "
                "HTML. Requires user approval.",
                {
                    "space_key": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "parent_id": {"type": "string"},
                },
                ["space_key", "title", "body"],
            ),
            approval=True,
            caps=["confluence", "write"],
        )
    )

    return tools


def make_linear_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Linear connector tools."""
    _ = roots
    tools: list[Callable[..., Any]] = []

    def linear_search_issues(query: str, max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "linear", "api_key")
        if err:
            return err
        gql = (
            "query($term: String!, $first: Int!) {"
            " searchIssues(term: $term, first: $first) {"
            " nodes { identifier title url state { name } assignee { name } } } }"
        )
        return _linear_gql(
            request_fn,
            connector_profile["api_key"],
            gql,
            {"term": query, "first": clamp(max_results)},
        )

    linear_search_issues.__name__ = "linear_search_issues"
    tools.append(
        attach(
            linear_search_issues,
            schema(
                "linear_search_issues",
                "Search Linear issues by text.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["linear", "read"],
        )
    )

    def linear_get_issue(issue_id: str) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "linear", "api_key")
        if err:
            return err
        gql = (
            "query($id: String!) { issue(id: $id) {"
            " identifier title description url state { name } assignee { name }"
            " comments { nodes { body user { name } } } } }"
        )
        return _linear_gql(
            request_fn, connector_profile["api_key"], gql, {"id": issue_id}
        )

    linear_get_issue.__name__ = "linear_get_issue"
    tools.append(
        attach(
            linear_get_issue,
            schema(
                "linear_get_issue",
                "Read a Linear issue (with comments) by ID or key like ENG-123.",
                {"issue_id": {"type": "string"}},
                ["issue_id"],
            ),
            caps=["linear", "read"],
        )
    )

    def linear_list_teams() -> dict[str, Any]:
        connector_profile, err = profile(secrets, "linear", "api_key")
        if err:
            return err
        return _linear_gql(
            request_fn,
            connector_profile["api_key"],
            "{ teams { nodes { id key name } } }",
            {},
        )

    linear_list_teams.__name__ = "linear_list_teams"
    tools.append(
        attach(
            linear_list_teams,
            schema(
                "linear_list_teams",
                "List Linear teams (IDs are needed to create issues).",
                {},
                [],
            ),
            caps=["linear", "read"],
        )
    )

    def linear_create_issue(
        team_id: str, title: str, description: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "linear", "api_key")
        if err:
            return err
        gql = (
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) {"
            " success issue { identifier url } } }"
        )
        return _linear_gql(
            request_fn,
            connector_profile["api_key"],
            gql,
            {"input": {"teamId": team_id, "title": title, "description": description}},
        )

    linear_create_issue.__name__ = "linear_create_issue"
    tools.append(
        attach(
            linear_create_issue,
            schema(
                "linear_create_issue",
                "Create a Linear issue. Get team_id from linear_list_teams. "
                "Requires user approval.",
                {
                    "team_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["team_id", "title"],
            ),
            approval=True,
            caps=["linear", "write"],
        )
    )

    return tools


def make_gitlab_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build GitLab connector tools."""
    _ = roots
    tools: list[Callable[..., Any]] = []

    def gitlab_search(
        query: str, scope: str = "issues", max_results: int = 10
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "gitlab", "token")
        if err:
            return err
        kind = scope if scope in ("projects", "issues", "merge_requests") else "issues"
        return request_fn(
            "GET",
            f"{_gitlab_api(connector_profile)}/search",
            headers={"PRIVATE-TOKEN": connector_profile["token"]},
            params={"scope": kind, "search": query, "per_page": clamp(max_results)},
        )

    gitlab_search.__name__ = "gitlab_search"
    tools.append(
        attach(
            gitlab_search,
            schema(
                "gitlab_search",
                "Search GitLab projects, issues, or merge_requests (scope).",
                {
                    "query": {"type": "string"},
                    "scope": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                ["query"],
            ),
            caps=["gitlab", "read"],
        )
    )

    def gitlab_get_issue(project: str, issue_iid: int) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "gitlab", "token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{_gitlab_api(connector_profile)}/projects/"
            f"{quote(project, safe='')}/issues/{issue_iid}",
            headers={"PRIVATE-TOKEN": connector_profile["token"]},
        )

    gitlab_get_issue.__name__ = "gitlab_get_issue"
    tools.append(
        attach(
            gitlab_get_issue,
            schema(
                "gitlab_get_issue",
                "Read a GitLab issue. project is an ID or full path like group/repo.",
                {"project": {"type": "string"}, "issue_iid": {"type": "integer"}},
                ["project", "issue_iid"],
            ),
            caps=["gitlab", "read"],
        )
    )

    def gitlab_get_merge_request(project: str, mr_iid: int) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "gitlab", "token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{_gitlab_api(connector_profile)}/projects/"
            f"{quote(project, safe='')}/merge_requests/{mr_iid}",
            headers={"PRIVATE-TOKEN": connector_profile["token"]},
        )

    gitlab_get_merge_request.__name__ = "gitlab_get_merge_request"
    tools.append(
        attach(
            gitlab_get_merge_request,
            schema(
                "gitlab_get_merge_request",
                "Read a GitLab merge request. project is an ID or full path like "
                "group/repo.",
                {"project": {"type": "string"}, "mr_iid": {"type": "integer"}},
                ["project", "mr_iid"],
            ),
            caps=["gitlab", "read"],
        )
    )

    def gitlab_create_issue(
        project: str, title: str, description: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "gitlab", "token")
        if err:
            return err
        return request_fn(
            "POST",
            f"{_gitlab_api(connector_profile)}/projects/"
            f"{quote(project, safe='')}/issues",
            headers={"PRIVATE-TOKEN": connector_profile["token"]},
            json={"title": title, "description": description},
        )

    gitlab_create_issue.__name__ = "gitlab_create_issue"
    tools.append(
        attach(
            gitlab_create_issue,
            schema(
                "gitlab_create_issue",
                "Create a GitLab issue. Requires user approval.",
                {
                    "project": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["project", "title"],
            ),
            approval=True,
            caps=["gitlab", "write"],
        )
    )

    return tools


def make_asana_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Asana connector tools."""
    _ = roots
    tools: list[Callable[..., Any]] = []

    def asana_list_workspaces() -> dict[str, Any]:
        connector_profile, err = profile(secrets, "asana", "token")
        if err:
            return err
        return request_fn(
            "GET",
            "https://app.asana.com/api/1.0/workspaces",
            headers=bearer_headers(connector_profile["token"]),
        )

    asana_list_workspaces.__name__ = "asana_list_workspaces"
    tools.append(
        attach(
            asana_list_workspaces,
            schema(
                "asana_list_workspaces",
                "List Asana workspaces (GIDs are needed to search tasks).",
                {},
                [],
            ),
            caps=["asana", "read"],
        )
    )

    def asana_search_tasks(
        workspace_gid: str, query: str, max_results: int = 10
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "asana", "token")
        if err:
            return err
        return request_fn(
            "GET",
            f"https://app.asana.com/api/1.0/workspaces/{workspace_gid}/typeahead",
            headers=bearer_headers(connector_profile["token"]),
            params={
                "resource_type": "task",
                "query": query,
                "count": clamp(max_results),
            },
        )

    asana_search_tasks.__name__ = "asana_search_tasks"
    tools.append(
        attach(
            asana_search_tasks,
            schema(
                "asana_search_tasks",
                "Search Asana tasks by name in a workspace. Get workspace_gid from "
                "asana_list_workspaces.",
                {
                    "workspace_gid": {"type": "string"},
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                ["workspace_gid", "query"],
            ),
            caps=["asana", "read"],
        )
    )

    def asana_get_task(task_gid: str) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "asana", "token")
        if err:
            return err
        return request_fn(
            "GET",
            f"https://app.asana.com/api/1.0/tasks/{task_gid}",
            headers=bearer_headers(connector_profile["token"]),
        )

    asana_get_task.__name__ = "asana_get_task"
    tools.append(
        attach(
            asana_get_task,
            schema(
                "asana_get_task",
                "Read an Asana task.",
                {"task_gid": {"type": "string"}},
                ["task_gid"],
            ),
            caps=["asana", "read"],
        )
    )

    def asana_create_task(
        project_gid: str, name: str, notes: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "asana", "token")
        if err:
            return err
        return request_fn(
            "POST",
            "https://app.asana.com/api/1.0/tasks",
            headers=bearer_headers(connector_profile["token"]),
            json={"data": {"name": name, "notes": notes, "projects": [project_gid]}},
        )

    asana_create_task.__name__ = "asana_create_task"
    tools.append(
        attach(
            asana_create_task,
            schema(
                "asana_create_task",
                "Create an Asana task in a project. Requires user approval.",
                {
                    "project_gid": {"type": "string"},
                    "name": {"type": "string"},
                    "notes": {"type": "string"},
                },
                ["project_gid", "name"],
            ),
            approval=True,
            caps=["asana", "write"],
        )
    )

    return tools


def make_clickup_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build ClickUp connector tools."""
    _ = roots
    tools: list[Callable[..., Any]] = []
    clickup_base = "https://api.clickup.com/api/v2"

    def clickup_list_teams() -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{clickup_base}/team",
            headers={"Authorization": connector_profile["api_token"]},
        )

    clickup_list_teams.__name__ = "clickup_list_teams"
    tools.append(
        attach(
            clickup_list_teams,
            schema(
                "clickup_list_teams",
                "List ClickUp workspaces (team ids are needed to browse spaces).",
                {},
                [],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_list_spaces(team_id: str) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{clickup_base}/team/{quote(team_id)}/space",
            headers={"Authorization": connector_profile["api_token"]},
        )

    clickup_list_spaces.__name__ = "clickup_list_spaces"
    tools.append(
        attach(
            clickup_list_spaces,
            schema(
                "clickup_list_spaces",
                "List spaces in a ClickUp workspace.",
                {"team_id": {"type": "string"}},
                ["team_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_list_lists(space_id: str) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{clickup_base}/space/{quote(space_id)}/list",
            headers={"Authorization": connector_profile["api_token"]},
        )

    clickup_list_lists.__name__ = "clickup_list_lists"
    tools.append(
        attach(
            clickup_list_lists,
            schema(
                "clickup_list_lists",
                "List folderless lists in a ClickUp space (list ids hold the tasks).",
                {"space_id": {"type": "string"}},
                ["space_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_list_tasks(
        list_id: str, include_closed: bool = False, max_results: int = 10
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{clickup_base}/list/{quote(list_id)}/task",
            headers={"Authorization": connector_profile["api_token"]},
            params={
                "include_closed": str(bool(include_closed)).lower(),
                "page": 0,
            },
        )

    clickup_list_tasks.__name__ = "clickup_list_tasks"
    tools.append(
        attach(
            clickup_list_tasks,
            schema(
                "clickup_list_tasks",
                "List tasks in a ClickUp list.",
                {
                    "list_id": {"type": "string"},
                    "include_closed": {"type": "boolean"},
                    "max_results": {"type": "integer"},
                },
                ["list_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_get_task(task_id: str) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{clickup_base}/task/{quote(task_id)}",
            headers={"Authorization": connector_profile["api_token"]},
            params={"include_subtasks": "true"},
        )

    clickup_get_task.__name__ = "clickup_get_task"
    tools.append(
        attach(
            clickup_get_task,
            schema(
                "clickup_get_task",
                "Read a ClickUp task (with subtasks) by id.",
                {"task_id": {"type": "string"}},
                ["task_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_create_task(
        list_id: str, name: str, description: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        return request_fn(
            "POST",
            f"{clickup_base}/list/{quote(list_id)}/task",
            headers={"Authorization": connector_profile["api_token"]},
            json={"name": name, "description": description},
        )

    clickup_create_task.__name__ = "clickup_create_task"
    tools.append(
        attach(
            clickup_create_task,
            schema(
                "clickup_create_task",
                "Create a ClickUp task in a list. Requires user approval.",
                {
                    "list_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["list_id", "name"],
            ),
            approval=True,
            caps=["clickup", "write"],
        )
    )

    def clickup_update_task(
        task_id: str, name: str = "", description: str = "", status: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        if status:
            body["status"] = status
        if not body:
            return {"error": "nothing to update: pass name, description, or status"}
        return request_fn(
            "PUT",
            f"{clickup_base}/task/{quote(task_id)}",
            headers={"Authorization": connector_profile["api_token"]},
            json=body,
        )

    clickup_update_task.__name__ = "clickup_update_task"
    tools.append(
        attach(
            clickup_update_task,
            schema(
                "clickup_update_task",
                "Update a ClickUp task's name, description, or status. Requires "
                "user approval.",
                {
                    "task_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string"},
                },
                ["task_id"],
            ),
            approval=True,
            caps=["clickup", "write"],
        )
    )

    def clickup_add_comment(task_id: str, text: str) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "clickup", "api_token")
        if err:
            return err
        return request_fn(
            "POST",
            f"{clickup_base}/task/{quote(task_id)}/comment",
            headers={"Authorization": connector_profile["api_token"]},
            json={"comment_text": text},
        )

    clickup_add_comment.__name__ = "clickup_add_comment"
    tools.append(
        attach(
            clickup_add_comment,
            schema(
                "clickup_add_comment",
                "Comment on a ClickUp task. Requires user approval.",
                {"task_id": {"type": "string"}, "text": {"type": "string"}},
                ["task_id", "text"],
            ),
            approval=True,
            caps=["clickup", "write"],
        )
    )

    return tools


def make_work_management_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build work-management tools in their legacy relative order."""
    tools: list[Callable[..., Any]] = []
    for factory in (
        make_jira_tools,
        make_confluence_tools,
        make_linear_tools,
        make_gitlab_tools,
        make_asana_tools,
        make_clickup_tools,
    ):
        tools.extend(factory(secrets, roots=roots, request_fn=request_fn))
    return tools


__all__ = [
    "make_asana_tools",
    "make_clickup_tools",
    "make_confluence_tools",
    "make_gitlab_tools",
    "make_jira_tools",
    "make_linear_tools",
    "make_work_management_tools",
]
