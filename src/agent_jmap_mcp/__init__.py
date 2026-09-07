"""agent-jmap-mcp: Stateless JMAP client and FastMCP server for AI agents."""

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.models import (
    EmailAddress,
    EmailHeader,
    EmailMessage,
    EmailThread,
    MailboxInfo,
    TriageCategory,
    TriageResult,
)

__version__ = "0.2.0"
__all__ = [
    "EmailAddress",
    "EmailHeader",
    "EmailMessage",
    "EmailThread",
    "JMAPClient",
    "MailboxInfo",
    "TriageCategory",
    "TriageResult",
    "__version__",
]
