"""Typed domain models for JMAP operations and MCP tool payloads."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class EmailAddress(BaseModel):
    """RFC 5322 formatted email address."""
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, description="Display name of the sender/recipient")
    email: str = Field(..., description="Email address string")

    def format_string(self) -> str:
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email


class EmailHeader(BaseModel):
    """Summary header of an email for list and search queries."""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique JMAP Email ID")
    blob_id: Optional[str] = Field(None, alias="blobId", description="Binary blob ID")
    thread_id: Optional[str] = Field(None, alias="threadId", description="Conversation thread ID")
    subject: str = Field("(no subject)", description="Email subject line")
    from_addr: List[EmailAddress] = Field(default_factory=list, alias="from", description="Senders")
    to: List[EmailAddress] = Field(default_factory=list, description="Direct recipients")
    received_at: str = Field(..., alias="receivedAt", description="ISO timestamp when the email was received")
    preview: str = Field("", description="Short plain text snippet preview")
    unread: bool = Field(False, description="True if email is unread ($seen keyword absent)")
    keywords: Dict[str, bool] = Field(default_factory=dict, description="JMAP keywords/flags")


class EmailMessage(BaseModel):
    """Full structured email content."""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique JMAP Email ID")
    blob_id: Optional[str] = Field(None, alias="blobId", description="Binary blob ID")
    thread_id: Optional[str] = Field(None, alias="threadId", description="Conversation thread ID")
    mailbox_ids: Dict[str, bool] = Field(default_factory=dict, alias="mailboxIds", description="Mailboxes containing this email")
    keywords: Dict[str, bool] = Field(default_factory=dict, description="Keywords/flags on this email")
    received_at: str = Field(..., alias="receivedAt", description="ISO timestamp when received")
    from_addr: List[EmailAddress] = Field(default_factory=list, alias="from")
    to: List[EmailAddress] = Field(default_factory=list)
    cc: List[EmailAddress] = Field(default_factory=list)
    bcc: List[EmailAddress] = Field(default_factory=list)
    reply_to: List[EmailAddress] = Field(default_factory=list, alias="replyTo")
    subject: str = Field("(no subject)")
    body_text: str = Field("", description="Extracted plain text body")
    body_html: Optional[str] = Field(None, description="HTML body if available")
    has_attachments: bool = Field(False, description="Whether the email contains file attachments")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Attachment metadata")


class MailboxInfo(BaseModel):
    """Metadata about a JMAP mailbox/folder."""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Unique JMAP Mailbox ID")
    name: str = Field(..., description="Display name of the mailbox (e.g. INBOX, Archive)")
    role: Optional[str] = Field(None, description="Standard role (inbox, sent, drafts, trash, archive, spam)")
    total_emails: int = Field(0, alias="totalEmails", description="Total email count in this mailbox")
    unread_emails: int = Field(0, alias="unreadEmails", description="Unread email count in this mailbox")


class TriageCategory(BaseModel):
    """Categorization entry for an email during automated inbox triage."""
    model_config = ConfigDict(populate_by_name=True)

    email_id: str
    subject: str
    from_address: str
    category: str = Field(..., description="Category: urgent, action_needed, newsletter, notification, personal, spam")
    priority: int = Field(..., description="Priority ranking from 1 (highest) to 5 (lowest)")
    summary: str = Field(..., description="Brief one-sentence action summary")


class TriageResult(BaseModel):
    """Aggregated inbox triage digest."""
    model_config = ConfigDict(populate_by_name=True)

    mailbox: str
    analyzed_count: int
    categories: List[TriageCategory] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
