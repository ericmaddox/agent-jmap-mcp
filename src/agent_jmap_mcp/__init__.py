"""agent-jmap-mcp: Modern JMAP Email Client and MCP Server for AI Agents."""

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.models import EmailAddress, EmailHeader, EmailMessage, MailboxInfo, TriageResult

__version__ = "0.1.0"
__all__ = [
    "EmailAddress",
    "EmailHeader",
    "EmailMessage",
    "JMAPClient",
    "MailboxInfo",
    "TriageResult",
    "__version__",
]
