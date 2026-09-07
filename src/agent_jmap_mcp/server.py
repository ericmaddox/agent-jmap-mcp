"""Model Context Protocol (MCP) Server for JMAP Email Operations."""

import json
import logging
import os

from mcp.server.fastmcp import FastMCP

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.triage import triage_mailbox

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("agent-jmap-mcp")

# Initialize FastMCP Server
mcp = FastMCP("agent-jmap-mcp")


def _get_client() -> JMAPClient:
    """Instantiate JMAPClient from environment variables."""
    session_url = os.environ.get("JMAP_SESSION_URL") or os.environ.get("JMAP_URL")
    token = os.environ.get("JMAP_API_TOKEN") or os.environ.get("JMAP_TOKEN") or ""
    account_id = os.environ.get("JMAP_ACCOUNT_ID")

    if not session_url:
        raise ValueError(
            "JMAP_SESSION_URL environment variable is required. "
            "Example: https://api.fastmail.com/jmap/session"
        )

    return JMAPClient(session_url=session_url, token=token, account_id=account_id)


@mcp.tool()
def jmap_list_mailboxes() -> str:
    """List all available mailboxes/folders in the email account (e.g. INBOX, Sent, Drafts, Archive)."""
    client = _get_client()
    mailboxes = client.get_mailboxes()
    return json.dumps([mb.model_dump() for mb in mailboxes], indent=2)


@mcp.tool()
def jmap_list_emails(
    mailbox: str = "INBOX",
    limit: int = 10,
    unread_only: bool = False,
    query: str | None = None,
) -> str:
    """List emails from a specified mailbox with subject, sender, date, unread flag, and preview snippet.

    Args:
        mailbox: Target mailbox name or role (default: INBOX, or Sent, Drafts, Archive, Trash).
        limit: Maximum number of emails to retrieve (default: 10, max: 50).
        unread_only: If true, filters only unread emails ($seen absent).
        query: Optional search keyword to filter by sender, subject, or content.
    """
    client = _get_client()
    emails = client.list_emails(
        mailbox_name=mailbox,
        limit=min(limit, 50),
        unread_only=unread_only,
        query_text=query,
    )
    return json.dumps([e.model_dump(by_alias=True) for e in emails], indent=2)


@mcp.tool()
def jmap_get_email(email_id: str, mark_as_read: bool = False) -> str:
    """Retrieve the complete content and structured details of an email by its JMAP ID.

    Args:
        email_id: Unique JMAP Email ID obtained from jmap_list_emails or triage.
        mark_as_read: If true, automatically sets the $seen keyword on the email.
    """
    client = _get_client()
    email_obj = client.get_email(email_id=email_id, mark_as_read=mark_as_read)
    if not email_obj:
        return json.dumps({"error": f"Email with ID '{email_id}' was not found."}, indent=2)
    return json.dumps(email_obj.model_dump(by_alias=True), indent=2)


@mcp.tool()
def jmap_send_email(
    to: list[str],
    subject: str,
    body: str,
    from_address: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    draft_only: bool = False,
) -> str:
    """Send an email or create an email draft atomically using JMAP Email/set and EmailSubmission/set.

    Args:
        to: List of recipient email addresses.
        subject: Email subject line.
        body: Plain text body content of the email message.
        from_address: Optional explicit sender address (defaults to primary account address).
        cc: Optional list of CC recipient email addresses.
        bcc: Optional list of BCC recipient email addresses.
        draft_only: If true, saves the message to the Drafts mailbox without submitting.
    """
    client = _get_client()
    result = client.send_email(
        to=to,
        subject=subject,
        body=body,
        from_addr=from_address,
        cc=cc,
        bcc=bcc,
        draft_only=draft_only,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def jmap_triage_inbox(
    mailbox: str = "INBOX",
    limit: int = 15,
    unread_only: bool = True,
) -> str:
    """Automatically analyze, categorize, and prioritize emails in a mailbox to generate an action digest.

    Categories assigned:
    - urgent (security alerts, 2FA, immediate action)
    - action_needed (invoices, billing, calendar commitments)
    - personal (direct communications)
    - notification (CI/CD, monitoring, system alerts)
    - newsletter (marketing, digests)

    Args:
        mailbox: Mailbox to analyze (default: INBOX).
        limit: Number of emails to inspect (default: 15).
        unread_only: Whether to restrict triage to unread emails only.
    """
    client = _get_client()
    triage_result = triage_mailbox(
        client=client,
        mailbox_name=mailbox,
        limit=limit,
        unread_only=unread_only,
    )
    return json.dumps(triage_result.model_dump(), indent=2)


def main() -> None:
    """Entry point for running the stdio MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
