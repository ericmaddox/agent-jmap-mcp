"""Automated email triage, categorization, and digest generation for AI agents."""

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.models import TriageCategory, TriageResult


def classify_email(subject: str, sender: str, preview: str) -> tuple[str, int, str]:
    """Rule-based classifier returning (category, priority 1-5, summary)."""
    s_lower = subject.lower()
    snd_lower = sender.lower()
    p_lower = preview.lower()
    text = f"{s_lower} {snd_lower} {p_lower}"

    # Priority 1: Security, OTPs, urgent flags
    if any(
        k in text
        for k in [
            "security alert",
            "password reset",
            "urgent",
            "action required",
            "verify your account",
            "2fa",
            "verification code",
        ]
    ):
        return "urgent", 1, "Immediate user attention or security verification required."

    # Priority 2: Invoices, Billing, Direct Requests
    if any(
        k in text
        for k in [
            "invoice",
            "receipt",
            "payment",
            "billing",
            "due date",
            "scheduled meeting",
            "calendar invite",
        ]
    ):
        return "action_needed", 2, "Financial transaction or scheduled commitment."

    # Priority 3: Personal or Direct Conversations
    if not any(
        k in snd_lower for k in ["no-reply", "noreply", "newsletter", "marketing", "updates"]
    ) and any(k in text for k in ["hey", "hi", "thanks", "meeting", "project", "review"]):
        return "personal", 3, "Direct correspondence from contact."

    # Priority 4: Notifications & Automated System Updates
    if any(
        k in text
        for k in ["build", "github", "jira", "deploy", "alert", "monitoring", "notification"]
    ):
        return "notification", 4, "Automated CI/CD or platform notification."

    # Priority 5: Newsletters & Marketing
    if any(k in text for k in ["newsletter", "unsubscribe", "digest", "weekly", "promo", "deal"]):
        return "newsletter", 5, "Marketing, subscription, or recurring digest."

    return "general", 3, "Standard inbox message."


def triage_mailbox(
    client: JMAPClient,
    mailbox_name: str = "INBOX",
    limit: int = 15,
    unread_only: bool = True,
) -> TriageResult:
    """Analyze and summarize a mailbox with structured action categories."""
    emails = client.list_emails(mailbox_name=mailbox_name, limit=limit, unread_only=unread_only)

    categories: list[TriageCategory] = []
    actions: list[str] = []

    for item in emails:
        sender_str = ", ".join([a.format_string() for a in item.from_addr])
        cat, prio, summary = classify_email(item.subject, sender_str, item.preview)

        categories.append(
            TriageCategory(
                email_id=item.id,
                subject=item.subject,
                from_address=sender_str,
                category=cat,
                priority=prio,
                summary=summary,
            )
        )

        if prio <= 2:
            actions.append(f"[{cat.upper()}] '{item.subject}' from {sender_str}")

    # Sort categories by priority ascending (1 highest)
    categories.sort(key=lambda x: x.priority)

    return TriageResult(
        mailbox=mailbox_name,
        analyzed_count=len(emails),
        categories=categories,
        recommended_actions=actions,
    )
