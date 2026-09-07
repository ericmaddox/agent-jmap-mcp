"""Command-line interface for JMAP Email Client and Server."""

import argparse
import json
import os
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.server import main as run_mcp_server
from agent_jmap_mcp.triage import triage_mailbox

console = Console()


def format_addresses(addr_list: Any) -> str:
    if not isinstance(addr_list, list):
        return str(addr_list or "")
    formatted = []
    for item in addr_list:
        if hasattr(item, "format_string"):
            formatted.append(item.format_string())
        elif isinstance(item, dict):
            name = item.get("name")
            email = item.get("email", "")
            formatted.append(f"{name} <{email}>" if name else email)
        else:
            formatted.append(str(item))
    return ", ".join(formatted)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agent-jmap",
        description="Stateless, atomic JMAP email client and MCP server for AI agents.",
    )
    parser.add_argument("--session-url", help="JMAP Session URL (env: JMAP_SESSION_URL)")
    parser.add_argument("--token", help="Bearer API Token (env: JMAP_API_TOKEN)")
    parser.add_argument("--account-id", help="JMAP Account ID (auto-discovered if omitted)")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON output")

    subparsers = parser.add_subparsers(dest="command")

    # mcp server command
    subparsers.add_parser("serve", help="Run the Model Context Protocol (MCP) stdio server")

    # mailboxes command
    subparsers.add_parser("mailboxes", help="List all mailboxes/folders")

    # list command
    list_p = subparsers.add_parser("list", help="List emails from a mailbox")
    list_p.add_argument("--mailbox", default="INBOX", help="Mailbox name or role (default: INBOX)")
    list_p.add_argument("--limit", type=int, default=10, help="Max emails to return (default: 10)")
    list_p.add_argument("--unread", action="store_true", help="Filter unread emails only")
    list_p.add_argument("--query", help="Keyword search query")

    # get command
    get_p = subparsers.add_parser("get", help="Retrieve full email content by ID")
    get_p.add_argument("id", help="JMAP Email ID")
    get_p.add_argument("--read", action="store_true", help="Mark email as read ($seen)")

    # send command
    send_p = subparsers.add_parser("send", help="Send or draft an email atomically")
    send_p.add_argument("--to", required=True, nargs="+", help="Recipient email addresses")
    send_p.add_argument("--subject", required=True, help="Subject line")
    send_p.add_argument("--body", required=True, help="Plain text message body")
    send_p.add_argument("--from-addr", help="Sender email address")
    send_p.add_argument("--cc", nargs="+", help="CC recipients")
    send_p.add_argument("--bcc", nargs="+", help="BCC recipients")
    send_p.add_argument("--draft", action="store_true", help="Save as draft without sending")

    # triage command
    triage_p = subparsers.add_parser("triage", help="Triage, categorize, and prioritize inbox")
    triage_p.add_argument("--mailbox", default="INBOX", help="Mailbox to triage")
    triage_p.add_argument("--limit", type=int, default=15, help="Number of emails to analyze")
    triage_p.add_argument("--all", action="store_true", help="Include read emails as well")

    args = parser.parse_args()

    if args.command == "serve":
        run_mcp_server()
        return 0

    if not args.command:
        parser.print_help()
        return 1

    session_url = (
        args.session_url or os.environ.get("JMAP_SESSION_URL") or os.environ.get("JMAP_URL")
    )
    token = args.token or os.environ.get("JMAP_API_TOKEN") or os.environ.get("JMAP_TOKEN") or ""
    account_id = args.account_id or os.environ.get("JMAP_ACCOUNT_ID")

    if not session_url:
        console.print(
            "[bold red]Error:[/bold red] JMAP Session URL is required. Set JMAP_SESSION_URL or use --session-url."
        )
        return 1

    client = JMAPClient(session_url=session_url, token=token, account_id=account_id)

    try:
        if args.command == "mailboxes":
            mbs = client.get_mailboxes()
            if args.json:
                print(json.dumps([mb.model_dump() for mb in mbs], indent=2))
            else:
                table = Table(title="JMAP Mailboxes")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="bold")
                table.add_column("Role", style="green")
                table.add_column("Total", justify="right")
                table.add_column("Unread", justify="right", style="magenta")
                for mb in mbs:
                    table.add_row(
                        mb.id, mb.name, mb.role or "-", str(mb.totalEmails), str(mb.unreadEmails)
                    )
                console.print(table)

        elif args.command == "list":
            emails = client.list_emails(
                mailbox_name=args.mailbox,
                limit=args.limit,
                unread_only=args.unread,
                query_text=args.query,
            )
            if args.json:
                print(json.dumps([e.model_dump(by_alias=True) for e in emails], indent=2))
            else:
                table = Table(title=f"Emails in {args.mailbox} (Limit: {args.limit})")
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("Date", style="blue")
                table.add_column("From", style="green")
                table.add_column("Subject", style="bold")
                table.add_column("Unread", justify="center")
                for e in emails:
                    unread_marker = "[bold red]●[/bold red]" if e.unread else "[dim]○[/dim]"
                    table.add_row(
                        e.id,
                        e.receivedAt[:16].replace("T", " "),
                        format_addresses(e.from_addr),
                        e.subject,
                        unread_marker,
                    )
                console.print(table)

        elif args.command == "get":
            email_msg = client.get_email(email_id=args.id, mark_as_read=args.read)
            if not email_msg:
                console.print(f"[bold red]Error:[/bold red] Email ID '{args.id}' not found.")
                return 1
            if args.json:
                print(json.dumps(email_msg.model_dump(by_alias=True), indent=2))
            else:
                console.print(f"[bold cyan]ID:[/bold cyan] {email_msg.id}")
                console.print(f"[bold cyan]Subject:[/bold cyan] [bold]{email_msg.subject}[/bold]")
                console.print(
                    f"[bold cyan]From:[/bold cyan] {format_addresses(email_msg.from_addr)}"
                )
                console.print(f"[bold cyan]To:[/bold cyan] {format_addresses(email_msg.to)}")
                if email_msg.cc:
                    console.print(f"[bold cyan]CC:[/bold cyan] {format_addresses(email_msg.cc)}")
                console.print(f"[bold cyan]Date:[/bold cyan] {email_msg.receivedAt}")
                console.print("-" * 60)
                console.print(email_msg.body_text or "[dim](empty body)[/dim]")

        elif args.command == "send":
            res = client.send_email(
                to=args.to,
                subject=args.subject,
                body=args.body,
                from_addr=args.from_addr,
                cc=args.cc,
                bcc=args.bcc,
                draft_only=args.draft,
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                action = "Draft created" if args.draft else "Email sent successfully"
                console.print(
                    f"[bold green]✓ {action}![/bold green] Email ID: [cyan]{res.get('emailId')}[/cyan]"
                )

        elif args.command == "triage":
            res = triage_mailbox(
                client=client, mailbox_name=args.mailbox, limit=args.limit, unread_only=not args.all
            )
            if args.json:
                print(json.dumps(res.model_dump(), indent=2))
            else:
                table = Table(title=f"Inbox Triage Digest — {args.mailbox}")
                table.add_column("Prio", justify="center", style="bold")
                table.add_column("Category", style="magenta")
                table.add_column("From", style="green")
                table.add_column("Subject", style="bold")
                table.add_column("Action Summary", style="yellow")
                for cat in res.categories:
                    table.add_row(
                        str(cat.priority),
                        cat.category.upper(),
                        cat.from_address[:25],
                        cat.subject[:30],
                        cat.summary,
                    )
                console.print(table)
                if res.recommended_actions:
                    console.print("\n[bold yellow]Recommended Action Items:[/bold yellow]")
                    for act in res.recommended_actions:
                        console.print(f" • {act}")

        return 0
    except Exception as e:  # noqa: BLE001
        console.print(f"[bold red]Execution Error:[/bold red] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
