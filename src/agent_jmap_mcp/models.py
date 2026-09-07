"""Typed domain models for JMAP operations and MCP tool payloads."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EmailAddress(BaseModel):
    """RFC 5322 formatted email address."""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(None, description="Display name of the sender/recipient")
    email: str = Field(..., description="Email address string")

    def format_string(self) -> str:
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email


class EmailHeader(BaseModel):
    """Summary header of an email for list and search queries."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique JMAP Email ID")
    blob_id: str | None = Field(None, alias="blobId", description="Binary blob ID")
    thread_id: str | None = Field(None, alias="threadId", description="Conversation thread ID")
    subject: str = Field("(no subject)", description="Email subject line")
    from_addr: list[EmailAddress] = Field(default_factory=list, alias="from", description="Senders")
    to: list[EmailAddress] = Field(default_factory=list, description="Direct recipients")
    received_at: str = Field(
        ..., alias="receivedAt", description="ISO timestamp when the email was received"
    )
    preview: str = Field("", description="Short plain text snippet preview")
    unread: bool = Field(False, description="True if email is unread ($seen keyword absent)")
    keywords: dict[str, bool] = Field(default_factory=dict, description="JMAP keywords/flags")


class EmailMessage(BaseModel):
    """Full structured email content."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique JMAP Email ID")
    blob_id: str | None = Field(None, alias="blobId", description="Binary blob ID")
    thread_id: str | None = Field(None, alias="threadId", description="Conversation thread ID")
    mailbox_ids: dict[str, bool] = Field(
        default_factory=dict, alias="mailboxIds", description="Mailboxes containing this email"
    )
    keywords: dict[str, bool] = Field(
        default_factory=dict, description="Keywords/flags on this email"
    )
    received_at: str = Field(..., alias="receivedAt", description="ISO timestamp when received")
    from_addr: list[EmailAddress] = Field(default_factory=list, alias="from")
    to: list[EmailAddress] = Field(default_factory=list)
    cc: list[EmailAddress] = Field(default_factory=list)
    bcc: list[EmailAddress] = Field(default_factory=list)
    reply_to: list[EmailAddress] = Field(default_factory=list, alias="replyTo")
    subject: str = Field("(no subject)")
    body_text: str = Field("", description="Extracted plain text or markdown body")
    body_html: str | None = Field(None, description="Raw HTML body if available")
    has_attachments: bool = Field(False, description="Whether the email contains file attachments")
    attachments: list[dict[str, Any]] = Field(
        default_factory=list, description="Attachment metadata"
    )


class EmailThread(BaseModel):
    """Structured conversation thread containing chronologically ordered messages."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique JMAP Thread ID")
    email_ids: list[str] = Field(
        default_factory=list, alias="emailIds", description="Ordered list of email IDs in thread"
    )
    messages: list[EmailMessage] = Field(
        default_factory=list, description="Chronologically ordered messages"
    )
    subject: str = Field("(no subject)", description="Thread subject line")
    message_count: int = Field(0, description="Total number of messages in thread")
    senders: list[str] = Field(
        default_factory=list, description="Unique senders participating in the thread"
    )
    has_attachments: bool = Field(
        False, description="Whether any message in the thread has attachments"
    )


class MailboxInfo(BaseModel):
    """Metadata about a JMAP mailbox/folder."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique JMAP Mailbox ID")
    name: str = Field(..., description="Display name of the mailbox (e.g. INBOX, Archive)")
    role: str | None = Field(
        None, description="Standard role (inbox, sent, drafts, trash, archive, spam)"
    )
    total_emails: int = Field(
        0, alias="totalEmails", description="Total email count in this mailbox"
    )
    unread_emails: int = Field(
        0, alias="unreadEmails", description="Unread email count in this mailbox"
    )


class TriageCategory(BaseModel):
    """Categorization entry for an email during automated inbox triage."""

    model_config = ConfigDict(populate_by_name=True)

    email_id: str
    subject: str
    from_address: str
    category: str = Field(
        ..., description="Category: urgent, action_needed, newsletter, notification, personal, spam"
    )
    priority: int = Field(..., description="Priority ranking from 1 (highest) to 5 (lowest)")
    summary: str = Field(..., description="Brief one-sentence action summary")


class TriageResult(BaseModel):
    """Aggregated inbox triage digest."""

    model_config = ConfigDict(populate_by_name=True)

    mailbox: str
    analyzed_count: int
    categories: list[TriageCategory] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
