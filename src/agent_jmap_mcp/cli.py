"""Command line interface (CLI) for agent-jmap operations and server execution."""

import argparse
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.server import mcp
from agent_jmap_mcp.triage import triage_inbox

console = Console()


def get_client_from_args(args: argparse.Namespace) -> JMAPClient:
    session_url = args.session_url or os.environ.get("JMAP_SESSION_URL")
    api_token = args.token or os.environ.get("JMAP_API_TOKEN")
    account_id = args.account or os.environ.get("JMAP_ACCOUNT_ID")

    if not session_url or not api_token:
        console.print(
            "[bold red]Error:[/bold red] Missing JMAP session URL or API token.\n"
            "Set JMAP_SESSION_URL and JMAP_API_TOKEN env vars or pass --session-url and --token."
        )
        sys.exit(1)

    return JMAPClient(session_url=session_url, token=api_token, account_id=account_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-jmap",
        description="Stateless JMAP Email Client and Model Context Protocol Server for AI Agents.",
    )
    parser.add_argument("--session-url", help="JMAP session discovery URL")
    parser.add_argument("--token", help="JMAP bearer API token")
    parser.add_argument("--account", help="Specific account ID (optional)")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # serve
    subparsers.add_parser("serve", help="Run the FastMCP stdio server")

    # mailboxes
    subparsers.add_parser("mailboxes", help="List all mailboxes/folders")

    # list
    list_p = subparsers.add_parser("list", help="List emails in a mailbox")
    list_p.add_argument("--mailbox", default="INBOX", help="Target mailbox (default: INBOX)")
    list_p.add_argument("--limit", type=int, default=15, help="Max results (default: 15)")
    list_p.add_argument("--unread", action="store_true", help="Filter unread emails only")
    list_p.add_argument("--query", help="Search text query")

    # get
    get_p = subparsers.add_parser("get", help="Get full details of an email by ID")
    get_p.add_argument("email_id", help="JMAP Email ID")
    get_p.add_argument("--read", action="store_true", help="Mark email as read")

    # thread
    thread_p = subparsers.add_parser("thread", help="View full conversation thread by Thread ID")
    thread_p.add_argument("thread_id", help="JMAP Thread ID")

    # download
    dl_p = subparsers.add_parser("download", help="Download an email attachment by blob ID")
    dl_p.add_argument("blob_id", help="JMAP Binary Blob ID")
    dl_p.add_argument("--name", required=True, help="Target filename for saving")
    dl_p.add_argument("--output", help="Output directory path (default: current directory)")

    # send
    send_p = subparsers.add_parser("send", help="Send an email atomically or save to Drafts")
    send_p.add_argument("--to", required=True, nargs="+", help="Recipient email address(es)")
    send_p.add_argument("--subject", required=True, help="Email subject")
    send_p.add_argument("--body", required=True, help="Email body text")
    send_p.add_argument("--from-addr", help="Sender email address")
    send_p.add_argument("--cc", nargs="+", help="CC recipient address(es)")
    send_p.add_argument("--bcc", nargs="+", help="BCC recipient address(es)")
    send_p.add_argument("--draft", action="store_true", help="Save to Drafts instead of sending")

    # triage
    triage_p = subparsers.add_parser("triage", help="Run automated inbox triage digest")
    triage_p.add_argument("--mailbox", default="INBOX", help="Mailbox to triage (default: INBOX)")
    triage_p.add_argument("--limit", type=int, default=20, help="Number of emails to analyze")
    triage_p.add_argument("--all", action="store_true", help="Include read emails in analysis")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "serve":
        mcp.run()
        return 0

    try:
        client = get_client_from_args(args)

        if args.command == "mailboxes":
            mailboxes = client.get_mailboxes()
            table = Table(title="JMAP Mailboxes", show_header=True, header_style="bold cyan")
            table.add_column("ID", style="dim")
            table.add_column("Name", style="bold")
            table.add_column("Role", style="magenta")
            table.add_column("Unread", justify="right", style="bold red")
            table.add_column("Total", justify="right")

            for mb in mailboxes:
                table.add_row(
                    mb.id,
                    mb.name,
                    mb.role or "-",
                    str(mb.unread_emails),
                    str(mb.total_emails),
                )
            console.print(table)

        elif args.command == "list":
            headers = client.list_emails(
                mailbox_name=args.mailbox,
                limit=args.limit,
                unread_only=args.unread,
                query=args.query,
            )
            table = Table(
                title=f"Emails in {args.mailbox} ({len(headers)})",
                show_header=True,
                header_style="bold cyan",
            )
            table.add_column("ID", style="dim")
            table.add_column("From", style="green")
            table.add_column("Subject", style="bold")
            table.add_column("Received", style="blue")
            table.add_column("Status")

            for h in headers:
                sender = h.from_addr[0].format_string() if h.from_addr else "Unknown"
                status = "[bold red]UNREAD[/bold red]" if h.unread else "[dim]READ[/dim]"
                table.add_row(h.id, sender, h.subject, h.received_at[:10], status)
            console.print(table)

        elif args.command == "get":
            msg = client.get_email(email_id=args.email_id, mark_as_read=args.read)
            if not msg:
                console.print(f"[bold red]Error:[/bold red] Email {args.email_id} not found.")
                return 1

            sender = msg.from_addr[0].format_string() if msg.from_addr else "Unknown"
            recipients = ", ".join(t.format_string() for t in msg.to)
            header_info = f"[bold]From:[/bold] {sender}\n[bold]To:[/bold] {recipients}\n[bold]Date:[/bold] {msg.received_at}\n[bold]Thread ID:[/bold] {msg.thread_id or '-'}"
            if msg.attachments:
                att_names = ", ".join(a.get("name", "unnamed") for a in msg.attachments)
                header_info += f"\n[bold yellow]Attachments:[/bold yellow] {att_names}"

            console.print(
                Panel(
                    f"{header_info}\n\n{msg.body_text}",
                    title=f"[bold]{msg.subject}[/bold]",
                    border_style="cyan",
                )
            )

        elif args.command == "thread":
            thread = client.get_thread(thread_id=args.thread_id)
            if not thread:
                console.print(f"[bold red]Error:[/bold red] Thread {args.thread_id} not found.")
                return 1

            console.print(
                f"[bold cyan]Thread:[/bold cyan] {thread.subject} ({thread.message_count} messages, Senders: {', '.join(thread.senders)})"
            )
            for i, msg in enumerate(thread.messages, 1):
                sender = msg.from_addr[0].format_string() if msg.from_addr else "Unknown"
                console.print(
                    Panel(
                        f"[bold]From:[/bold] {sender} | [bold]Date:[/bold] {msg.received_at}\n\n{msg.body_text}",
                        title=f"Message #{i} ({msg.id})",
                        border_style="blue",
                    )
                )

        elif args.command == "download":
            out_dir = args.output or os.getcwd()
            content = client.download_attachment(
                blob_id=args.blob_id,
                filename=args.name,
                output_path=out_dir,
            )
            console.print(
                f"[bold green]Saved:[/bold green] {args.name} ({len(content)} bytes) to {out_dir}"
            )

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
            console.print(
                f"[bold green]Success:[/bold green] {res.get('status')} "
                f"(Email ID: {res.get('emailId')}, Submission ID: {res.get('submissionId')})"
            )

        elif args.command == "triage":
            res = triage_inbox(
                client=client,
                mailbox_name=args.mailbox,
                limit=args.limit,
                unread_only=not args.all,
            )
            table = Table(
                title=f"Triage Digest for {res.mailbox} ({res.analyzed_count} analyzed)",
                show_header=True,
                header_style="bold yellow",
            )
            table.add_column("Prio", justify="center", style="bold")
            table.add_column("Category", style="cyan")
            table.add_column("From", style="green")
            table.add_column("Subject", style="bold")
            table.add_column("Action Summary")

            for cat in res.categories:
                prio_style = (
                    "bold red" if cat.priority <= 2 else "yellow" if cat.priority == 3 else "dim"
                )
                table.add_row(
                    f"[{prio_style}]P{cat.priority}[/{prio_style}]",
                    cat.category,
                    cat.from_address,
                    cat.subject[:40],
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
