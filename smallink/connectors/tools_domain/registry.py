"""Explicit order for connector tool factories migrated from the legacy host.

The connector composition entry point owns filtering. This module is only the
deterministic data needed by that composition root; it deliberately performs no
module discovery or configuration loading.
"""

from __future__ import annotations

from typing import Any, Callable

from .browser import make_browser_tools
from .crm_analytics import (
    make_amplitude_tools,
    make_apollo_tools,
    make_attio_tools,
    make_close_tools,
    make_hubspot_tools,
    make_hunter_tools,
    make_mixpanel_tools,
    make_notion_tools,
    make_posthog_tools,
)
from .design_commerce import (
    make_canva_tools,
    make_discord_tools,
    make_docusign_tools,
    make_figma_tools,
    make_stripe_tools,
    make_zendesk_tools,
)
from .files_business import (
    make_box_tools,
    make_drive_tools,
    make_dropbox_tools,
    make_quickbooks_tools,
    make_whatsapp_tools,
)
from .google_workspace import make_gcal_tools, make_gmail_tools
from .microsoft import make_outlook_tools
from .work_management import (
    make_asana_tools,
    make_clickup_tools,
    make_confluence_tools,
    make_gitlab_tools,
    make_jira_tools,
    make_linear_tools,
)

ToolFactory = Callable[..., list[Callable[..., Any]]]

# This order matches the legacy ``make_integration_tools`` append order.  Keep
# connector ids aligned with ``tool_defs.py`` because connector filtering uses
# those ids (not function-name prefixes).
MIGRATED_TOOL_FACTORIES: tuple[tuple[str, ToolFactory], ...] = (
    ("browser", make_browser_tools),
    ("gmail", make_gmail_tools),
    ("google_calendar", make_gcal_tools),
    ("outlook", make_outlook_tools),
    ("jira", make_jira_tools),
    ("confluence", make_confluence_tools),
    ("zendesk", make_zendesk_tools),
    ("linear", make_linear_tools),
    ("gitlab", make_gitlab_tools),
    ("discord", make_discord_tools),
    ("stripe", make_stripe_tools),
    ("asana", make_asana_tools),
    ("hubspot", make_hubspot_tools),
    ("dropbox", make_dropbox_tools),
    ("box", make_box_tools),
    ("quickbooks", make_quickbooks_tools),
    ("whatsapp", make_whatsapp_tools),
    ("notion", make_notion_tools),
    ("attio", make_attio_tools),
    ("posthog", make_posthog_tools),
    ("mixpanel", make_mixpanel_tools),
    ("amplitude", make_amplitude_tools),
    ("apollo", make_apollo_tools),
    ("hunter", make_hunter_tools),
    ("clickup", make_clickup_tools),
    ("close", make_close_tools),
    ("figma", make_figma_tools),
    ("google_drive", make_drive_tools),
    ("docusign", make_docusign_tools),
    ("canva", make_canva_tools),
)
