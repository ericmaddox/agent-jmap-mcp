"""FastMCP Model Context Protocol (MCP) Server for JMAP Email."""

import json
import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.triage import triage_inbox

logger = logging.getLogger("agent_jmap_mcp.server")

# Initialize FastMCP Server
mcp = FastMCP("jmap-email")


def get_client() -> JMAPClient:
    """Create a JMAPClient instance from environment variables."""
    session_url = os.environ.get("JMAP_SESSION_URL")
    api_token = os.environ.get("JMAP_API_TOKEN")
    account_id = os.environ.get("JMAP_ACCOUNT_ID")

    if not session_url or not api_token:
        raise ValueError(
            "Missing required environment variables. "
            "Ensure JMAP_SESSION_URL and JMAP_API_TOKEN are set in your MCP environment."
        )

    return JMAPClient(
        session_url=session_url,
        token=api_token,
        account_id=account_id,
    )


@mcp.tool()
def jmap_list_mailboxes() -> str:
    """List all available mailboxes/folders in the email account with unread and total email counts.

    Returns:
        JSON string containing list of mailboxes with id, name, role, unread count, total count.
    """
    client = get_client()
    mailboxes = client.get_mailboxes()
    return json.dumps([mb.model_dump(by_alias=True) for mb in mailboxes], indent=2)


@mcp.tool()
def jmap_list_emails(
    mailbox: str = "INBOX",
    limit: int = 20,
    unread_only: bool = False,
    query: str | None = None,
    from_address: str | None = None,
    subject_contains: str | None = None,
) -> str:
    """Search and list emails in a specific mailbox with header summaries.

    Args:
        mailbox: Mailbox name (e.g. INBOX, Sent, Archive, Trash) or Mailbox ID. Default is 'INBOX'.
        limit: Maximum number of emails to retrieve (default 20).
        unread_only: Filter only unread messages if True.
        query: General text search term matched across sender, subject, and body.
        from_address: Filter by sender email address.
        subject_contains: Filter by substring in email subject.

    Returns:
        JSON string containing list of email header summaries.
    """
    client = get_client()
    headers = client.list_emails(
        mailbox_name=mailbox,
        limit=limit,
        unread_only=unread_only,
        query=query,
        from_addr=from_address,
        subject_contains=subject_contains,
    )
    return json.dumps([h.model_dump(by_alias=True) for h in headers], indent=2)


@mcp.tool()
def jmap_get_email(
    email_id: str,
    mark_as_read: bool = False,
) -> str:
    """Retrieve full structured content of an email message including body text and attachments.

    Args:
        email_id: The unique JMAP email ID (obtained from jmap_list_emails).
        mark_as_read: If True, sets the $seen flag marking the email as read.

    Returns:
        JSON string containing complete EmailMessage structure.
    """
    client = get_client()
    msg = client.get_email(email_id=email_id, mark_as_read=mark_as_read)
    if not msg:
        return json.dumps({"error": f"Email not found with ID: {email_id}"})
    return json.dumps(msg.model_dump(by_alias=True), indent=2)


@mcp.tool()
def jmap_get_thread(
    thread_id: str,
) -> str:
    """Retrieve an entire conversation thread chronologically by Thread ID (RFC 8621 Thread/get).

    Args:
        thread_id: The unique JMAP thread ID (obtained from jmap_list_emails or jmap_get_email).

    Returns:
        JSON string containing the complete chronologically ordered conversation thread.
    """
    client = get_client()
    thread = client.get_thread(thread_id=thread_id)
    if not thread:
        return json.dumps({"error": f"Thread not found with ID: {thread_id}"})
    return json.dumps(thread.model_dump(by_alias=True), indent=2)


@mcp.tool()
def jmap_download_attachment(
    blob_id: str,
    filename: str,
    save_directory: str | None = None,
) -> str:
    """Download a binary email attachment by its blobId and optionally save to disk.

    Args:
        blob_id: The binary blob ID of the attachment (from jmap_get_email attachments list).
        filename: Target filename for the attachment.
        save_directory: Optional directory path to save the file. Defaults to current working directory.

    Returns:
        JSON string containing download confirmation, absolute saved path, and byte size.
    """
    client = get_client()
    target_dir = Path(save_directory) if save_directory else Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / filename

    content = client.download_attachment(
        blob_id=blob_id, filename=filename, output_path=str(out_path)
    )

    return json.dumps(
        {
            "status": "success",
            "blob_id": blob_id,
            "filename": filename,
            "saved_path": str(out_path.resolve()),
            "size_bytes": len(content),
        },
        indent=2,
    )


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
    """Compose and send an email atomically or save it as a draft via JMAP.

    Args:
        to: List of recipient email addresses (e.g. ["alice@example.com"]).
        subject: Subject line of the email.
        body: Plain text or markdown body content of the email.
        from_address: Optional sender email address.
        cc: Optional list of CC recipient email addresses.
        bcc: Optional list of BCC recipient email addresses.
        draft_only: If True, saves to Drafts folder without submitting for delivery.

    Returns:
        JSON string with result status, created emailId, and submissionId.
    """
    client = get_client()
    res = client.send_email(
        to=to,
        subject=subject,
        body=body,
        from_addr=from_address,
        cc=cc,
        bcc=bcc,
        draft_only=draft_only,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def jmap_triage_inbox(
    mailbox: str = "INBOX",
    limit: int = 20,
    unread_only: bool = True,
) -> str:
    """Analyze and triage recent emails in a mailbox, generating categorized digests and actionable steps.

    Args:
        mailbox: Mailbox to triage (default 'INBOX').
        limit: Number of recent emails to evaluate (default 20).
        unread_only: Evaluate only unread emails if True.

    Returns:
        JSON string with TriageResult digest, categorized emails, priorities (1-5), and recommended actions.
    """
    client = get_client()
    res = triage_inbox(client=client, mailbox_name=mailbox, limit=limit, unread_only=unread_only)
    return json.dumps(res.model_dump(by_alias=True), indent=2)


def main() -> None:
    """Main entrypoint for MCP stdio server."""
    mcp.run()


if __name__ == "__main__":
    main()
