"""MineM connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ..minem_client import get_minem_client
from ..tool_utils import attach, schema


def make_minem_tools() -> list[Callable[..., Any]]:
    """Build MineM read-only material tools."""
    minem = get_minem_client()
    tools: list[Callable[..., Any]] = []

    def minem_status() -> dict[str, Any]:
        return minem.status()

    minem_status.__name__ = "minem_status"
    tools.append(
        attach(
            minem_status,
            schema(
                "minem_status",
                "Check the connected MineM service and summarize its visible material counts.",
                {},
                [],
            ),
            caps=["minem", "read"],
        )
    )

    def minem_search_assets(
        query: str, asset_type: str = "all", limit: int = 10
    ) -> dict[str, Any]:
        return minem.search_assets(query, asset_type=asset_type, limit=limit)

    minem_search_assets.__name__ = "minem_search_assets"
    tools.append(
        attach(
            minem_search_assets,
            schema(
                "minem_search_assets",
                "Search MineM materials. Use asset_type all, report, page, or resource.",
                {
                    "query": {"type": "string"},
                    "asset_type": {
                        "type": "string",
                        "enum": ["all", "report", "page", "resource"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                ["query"],
            ),
            caps=["minem", "read"],
        )
    )

    def minem_get_asset(reference: str) -> dict[str, Any]:
        try:
            return minem.get_asset(reference)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    minem_get_asset.__name__ = "minem_get_asset"
    tools.append(
        attach(
            minem_get_asset,
            schema(
                "minem_get_asset",
                "Read one MineM report, page, or resource by asset code or ID.",
                {"reference": {"type": "string"}},
                ["reference"],
            ),
            caps=["minem", "read"],
        )
    )

    def minem_get_report_pages(reference: str, limit: int = 60) -> dict[str, Any]:
        try:
            return minem.get_report_pages(reference, limit=limit)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    minem_get_report_pages.__name__ = "minem_get_report_pages"
    tools.append(
        attach(
            minem_get_report_pages,
            schema(
                "minem_get_report_pages",
                "List pages belonging to a MineM report by report code or ID.",
                {
                    "reference": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                ["reference"],
            ),
            caps=["minem", "read"],
        )
    )

    def minem_get_versions(reference: str, limit: int = 20) -> dict[str, Any]:
        try:
            return minem.get_versions(reference, limit=limit)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    minem_get_versions.__name__ = "minem_get_versions"
    tools.append(
        attach(
            minem_get_versions,
            schema(
                "minem_get_versions",
                "List the known versions of a MineM asset.",
                {
                    "reference": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                ["reference"],
            ),
            caps=["minem", "read"],
        )
    )

    def minem_get_lineage(reference: str) -> dict[str, Any]:
        try:
            return minem.get_lineage(reference)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    minem_get_lineage.__name__ = "minem_get_lineage"
    tools.append(
        attach(
            minem_get_lineage,
            schema(
                "minem_get_lineage",
                "Read MineM provenance and relationships for an asset.",
                {"reference": {"type": "string"}},
                ["reference"],
            ),
            caps=["minem", "read"],
        )
    )

    return tools
