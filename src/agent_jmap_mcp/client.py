"""RFC 8620 and RFC 8621 compliant JMAP Client for modern email automation."""

import logging
import re
from pathlib import Path
from typing import Any

import html2text
import httpx

from agent_jmap_mcp.models import (
    EmailAddress,
    EmailHeader,
    EmailMessage,
    EmailThread,
    MailboxInfo,
)


def _format_address(addr: Any) -> dict[str, str]:
    if isinstance(addr, str):
        return {"email": addr.strip()}
    if hasattr(addr, "email"):
        entry = {"email": addr.email.strip()}
        if getattr(addr, "name", None):
            entry["name"] = addr.name.strip()
        return entry
    if isinstance(addr, dict) and "email" in addr:
        return addr
    return {"email": str(addr).strip()}


logger = logging.getLogger("agent_jmap_mcp.client")


class JMAPClient:
    """RFC 8620/8621 JMAP Client with atomic message creation and submission."""

    CAPABILITY_CORE = "urn:ietf:params:jmap:core"
    CAPABILITY_MAIL = "urn:ietf:params:jmap:mail"
    CAPABILITY_SUBMISSION = "urn:ietf:params:jmap:submission"

    def __init__(
        self,
        session_url: str,
        token: str | None = None,
        api_token: str | None = None,
        account_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.session_url = session_url.rstrip("/")
        auth_tok = token or api_token or ""
        self.token = auth_tok.strip()
        self.api_token = self.token
        self.account_id = account_id
        self.timeout = timeout

        self._api_url: str | None = None
        self._download_url: str | None = None
        self._upload_url: str | None = None

        # Setup html2text converter
        self._html_converter = html2text.HTML2Text()
        self._html_converter.ignore_links = False
        self._html_converter.ignore_images = False
        self._html_converter.body_width = 0

    @property
    def primary_mail_account_id(self) -> str | None:
        return self.account_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def discover_session(self) -> dict[str, Any]:
        """Discover JMAP server session capabilities and URLs (RFC 8620 Section 2)."""
        logger.debug("Querying JMAP session at: %s", self.session_url)
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self.session_url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()

        self._api_url = data.get("apiUrl")
        self._download_url = data.get("downloadUrl")
        self._upload_url = data.get("uploadUrl")

        if not self.account_id:
            primary_accounts = data.get("primaryAccounts", {})
            self.account_id = primary_accounts.get(self.CAPABILITY_MAIL) or primary_accounts.get(
                self.CAPABILITY_CORE
            )

            if not self.account_id and data.get("accounts"):
                # Fallback to the first account with mail capability
                for acc_id, acc_data in data["accounts"].items():
                    caps = acc_data.get("accountCapabilities", {})
                    if self.CAPABILITY_MAIL in caps:
                        self.account_id = acc_id
                        break

        if not self._api_url:
            raise ValueError("JMAP Session response missing 'apiUrl'.")

        return data

    def _ensure_session(self) -> None:
        if not self._api_url or not self.account_id:
            self.discover_session()

    def request(self, method_calls: list[list[Any]]) -> dict[str, Any]:
        """Execute a standard RFC 8620 JMAP POST request containing batch method calls."""
        self._ensure_session()
        payload = {
            "using": [
                self.CAPABILITY_CORE,
                self.CAPABILITY_MAIL,
                self.CAPABILITY_SUBMISSION,
            ],
            "methodCalls": method_calls,
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                self._api_url,  # type: ignore
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def get_mailboxes(self) -> list[MailboxInfo]:
        """Retrieve all accessible mailboxes/folders for the account."""
        self._ensure_session()
        calls = [
            [
                "Mailbox/get",
                {
                    "accountId": self.account_id,
                    "ids": None,
                },
                "c0",
            ]
        ]
        resp = self.request(calls)
        method_responses = resp.get("methodResponses", [])

        mailboxes: list[MailboxInfo] = []
        for name, args, _call_id in method_responses:
            if name == "Mailbox/get":
                for item in args.get("list", []):
                    mailboxes.append(
                        MailboxInfo(
                            id=item.get("id"),
                            name=item.get("name"),
                            role=item.get("role"),
                            total_emails=item.get("totalEmails", 0),
                            unread_emails=item.get("unreadEmails", 0),
                        )
                    )
        return mailboxes

    def resolve_mailbox_id(self, mailbox_name_or_role: str) -> str | None:
        """Resolve a mailbox ID from standard name (e.g. INBOX, Archive) or role (inbox, sent, drafts, etc.)."""
        mailboxes = self.get_mailboxes()
        target = mailbox_name_or_role.strip().lower()

        # Check by role first
        for mb in mailboxes:
            if mb.role and mb.role.lower() == target:
                return mb.id

        # Check by exact/case-insensitive name
        for mb in mailboxes:
            if mb.name.lower() == target:
                return mb.id

        # Check by raw ID
        for mb in mailboxes:
            if mb.id == mailbox_name_or_role:
                return mb.id

        return None

    def list_emails(
        self,
        mailbox_name: str = "INBOX",
        limit: int = 20,
        unread_only: bool = False,
        query: str | None = None,
        from_addr: str | None = None,
        subject_contains: str | None = None,
    ) -> list[EmailHeader]:
        """Query and return email headers matching the given filter criteria."""
        self._ensure_session()
        mailbox_id = self.resolve_mailbox_id(mailbox_name)

        filter_conditions: dict[str, Any] = {}
        if mailbox_id:
            filter_conditions["inMailbox"] = mailbox_id

        if unread_only:
            filter_conditions["hasKeyword"] = "$seen"
            # In JMAP, unread is absence of $seen: we use filter operator if needed or post-filter
            # Standard RFC 8621 filter: notKeyword: "$seen"
            filter_conditions.pop("hasKeyword")
            filter_conditions["notKeyword"] = "$seen"

        if query:
            filter_conditions["text"] = query
        if from_addr:
            filter_conditions["from"] = from_addr
        if subject_contains:
            filter_conditions["subject"] = subject_contains

        query_payload: dict[str, Any] = {
            "accountId": self.account_id,
            "filter": filter_conditions if filter_conditions else None,
            "sort": [{"property": "receivedAt", "isAscending": False}],
            "limit": limit,
            "calculateTotal": True,
        }

        # Query + back-reference Email/get in single batch request
        calls = [
            ["Email/query", query_payload, "q0"],
            [
                "Email/get",
                {
                    "accountId": self.account_id,
                    "#ids": {
                        "resultOf": "q0",
                        "name": "Email/query",
                        "path": "/ids",
                    },
                    "properties": [
                        "id",
                        "blobId",
                        "threadId",
                        "mailboxIds",
                        "keywords",
                        "receivedAt",
                        "from",
                        "to",
                        "subject",
                        "preview",
                    ],
                },
                "g0",
            ],
        ]

        resp = self.request(calls)
        headers: list[EmailHeader] = []

        for name, args, _ in resp.get("methodResponses", []):
            if name == "Email/get":
                for item in args.get("list", []):
                    from_list = [
                        EmailAddress(name=a.get("name"), email=a.get("email", ""))
                        for a in item.get("from", [])
                    ]
                    to_list = [
                        EmailAddress(name=a.get("name"), email=a.get("email", ""))
                        for a in item.get("to", [])
                    ]
                    keywords = item.get("keywords", {})
                    unread = not keywords.get("$seen", False)

                    headers.append(
                        EmailHeader(
                            id=item.get("id"),
                            blob_id=item.get("blobId"),
                            thread_id=item.get("threadId"),
                            subject=item.get("subject") or "(no subject)",
                            from_addr=from_list,
                            to=to_list,
                            received_at=item.get("receivedAt", ""),
                            preview=item.get("preview", ""),
                            unread=unread,
                            keywords=keywords,
                        )
                    )

        return headers

    def get_email(self, email_id: str, mark_as_read: bool = False) -> EmailMessage | None:
        """Fetch the full structured email content by ID."""
        self._ensure_session()

        calls = [
            [
                "Email/get",
                {
                    "accountId": self.account_id,
                    "ids": [email_id],
                    "fetchTextBodyValues": True,
                    "fetchHTMLBodyValues": True,
                    "properties": [
                        "id",
                        "blobId",
                        "threadId",
                        "mailboxIds",
                        "keywords",
                        "receivedAt",
                        "from",
                        "to",
                        "cc",
                        "bcc",
                        "replyTo",
                        "subject",
                        "bodyStructure",
                        "bodyValues",
                        "textBody",
                        "htmlBody",
                        "attachments",
                    ],
                },
                "g0",
            ]
        ]

        if mark_as_read:
            calls.append(
                [
                    "Email/set",
                    {
                        "accountId": self.account_id,
                        "update": {email_id: {"keywords/$seen": True}},
                    },
                    "u0",
                ]
            )

        resp = self.request(calls)
        email_item = None

        for name, args, _ in resp.get("methodResponses", []):
            if name == "Email/get":
                items = args.get("list", [])
                if items:
                    email_item = items[0]

        if not email_item:
            return None

        # Extract addresses
        from_list = [
            EmailAddress(name=a.get("name"), email=a.get("email", ""))
            for a in email_item.get("from", [])
        ]
        to_list = [
            EmailAddress(name=a.get("name"), email=a.get("email", ""))
            for a in email_item.get("to", [])
        ]
        cc_list = [
            EmailAddress(name=a.get("name"), email=a.get("email", ""))
            for a in email_item.get("cc", [])
        ]
        bcc_list = [
            EmailAddress(name=a.get("name"), email=a.get("email", ""))
            for a in email_item.get("bcc", [])
        ]
        reply_to_list = [
            EmailAddress(name=a.get("name"), email=a.get("email", ""))
            for a in email_item.get("replyTo", [])
        ]

        body_text, body_html, attachments = self._extract_body_and_attachments(email_item)

        return EmailMessage(
            id=email_item.get("id"),
            blob_id=email_item.get("blobId"),
            thread_id=email_item.get("threadId"),
            mailbox_ids=email_item.get("mailboxIds", {}),
            keywords=email_item.get("keywords", {}),
            received_at=email_item.get("receivedAt", ""),
            from_addr=from_list,
            to=to_list,
            cc=cc_list,
            bcc=bcc_list,
            reply_to=reply_to_list,
            subject=email_item.get("subject") or "(no subject)",
            body_text=body_text,
            body_html=body_html if body_html else None,
            has_attachments=len(attachments) > 0,
            attachments=attachments,
        )

    def _extract_body_and_attachments(
        self, item: dict[str, Any]
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """Extract body text (or markdown converted from HTML) and attachment metadata."""
        body_values = item.get("bodyValues", {})
        text_parts = item.get("textBody", [])
        html_parts = item.get("htmlBody", [])

        extracted_text = ""
        extracted_html = ""

        # Extract text/plain
        for part in text_parts:
            part_id = part.get("partId")
            if part_id and part_id in body_values:
                extracted_text += body_values[part_id].get("value", "")

        # Extract text/html
        for part in html_parts:
            part_id = part.get("partId")
            if part_id and part_id in body_values:
                extracted_html += body_values[part_id].get("value", "")

        # If text/plain was absent or empty, convert HTML to clean markdown for LLM consumption
        if not extracted_text.strip() and extracted_html.strip():
            try:
                extracted_text = self._html_converter.handle(extracted_html).strip()
            except Exception:
                extracted_text = re.sub(r"<[^>]+>", " ", extracted_html)
                extracted_text = re.sub(r"\s+", " ", extracted_text).strip()

        # Attachments metadata
        attachments: list[dict[str, Any]] = []
        for att in item.get("attachments", []):
            attachments.append(
                {
                    "blobId": att.get("blobId"),
                    "name": att.get("name", "unnamed_attachment"),
                    "type": att.get("type", "application/octet-stream"),
                    "size": att.get("size", 0),
                    "cid": att.get("cid"),
                }
            )

        return extracted_text.strip(), extracted_html.strip(), attachments

    def download_attachment(
        self,
        blob_id: str,
        filename: str | None = None,
        account_id: str | None = None,
        output_path: str | None = None,
    ) -> bytes:
        """Download binary attachment data via RFC 8620 downloadUrl template."""
        self._ensure_session()
        target_account_id = account_id or self.account_id

        if not self._download_url:
            raise RuntimeError("JMAP downloadUrl was not provided by server session.")

        name_part = filename or "attachment"
        url = (
            self._download_url.replace("{accountId}", target_account_id or "")
            .replace("{blobId}", blob_id)
            .replace("{name}", name_part)
        )

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers={"Authorization": f"Bearer {self.token}"})
            resp.raise_for_status()
            content = resp.content

        if output_path:
            out_file = Path(output_path)
            if out_file.is_dir():
                out_file = out_file / name_part
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(content)
            logger.info("Saved attachment (%d bytes) to %s", len(content), out_file)

        return content

    def get_thread(self, thread_id: str) -> EmailThread | None:
        """Fetch and aggregate an entire conversation thread chronologically (RFC 8621 Thread/get)."""
        self._ensure_session()

        calls = [
            [
                "Thread/get",
                {
                    "accountId": self.account_id,
                    "ids": [thread_id],
                },
                "t0",
            ],
            [
                "Email/get",
                {
                    "accountId": self.account_id,
                    "#ids": {
                        "resultOf": "t0",
                        "name": "Thread/get",
                        "path": "/list/0/emailIds",
                    },
                    "fetchTextBodyValues": True,
                    "fetchHTMLBodyValues": True,
                    "properties": [
                        "id",
                        "blobId",
                        "threadId",
                        "mailboxIds",
                        "keywords",
                        "receivedAt",
                        "from",
                        "to",
                        "cc",
                        "bcc",
                        "replyTo",
                        "subject",
                        "bodyStructure",
                        "bodyValues",
                        "textBody",
                        "htmlBody",
                        "attachments",
                    ],
                },
                "e0",
            ],
        ]

        resp = self.request(calls)
        email_ids: list[str] = []
        raw_emails: list[dict[str, Any]] = []

        for name, args, _ in resp.get("methodResponses", []):
            if name == "Thread/get":
                thread_list = args.get("list", [])
                if thread_list:
                    email_ids = thread_list[0].get("emailIds", [])
            elif name == "Email/get":
                raw_emails = args.get("list", [])

        if not email_ids and not raw_emails:
            return None

        # Map raw emails by ID
        email_map = {item.get("id"): item for item in raw_emails if item.get("id")}
        ordered_messages: list[EmailMessage] = []
        unique_senders: set[str] = set()
        has_attachments = False
        subject = "(no subject)"

        for eid in email_ids:
            if eid in email_map:
                item = email_map[eid]
                from_list = [
                    EmailAddress(name=a.get("name"), email=a.get("email", ""))
                    for a in item.get("from", [])
                ]
                to_list = [
                    EmailAddress(name=a.get("name"), email=a.get("email", ""))
                    for a in item.get("to", [])
                ]
                cc_list = [
                    EmailAddress(name=a.get("name"), email=a.get("email", ""))
                    for a in item.get("cc", [])
                ]
                bcc_list = [
                    EmailAddress(name=a.get("name"), email=a.get("email", ""))
                    for a in item.get("bcc", [])
                ]
                reply_to_list = [
                    EmailAddress(name=a.get("name"), email=a.get("email", ""))
                    for a in item.get("replyTo", [])
                ]

                for fa in from_list:
                    unique_senders.add(fa.format_string())

                body_text, body_html, attachments = self._extract_body_and_attachments(item)
                if attachments:
                    has_attachments = True

                if not subject or subject == "(no subject)":
                    subject = item.get("subject") or subject

                ordered_messages.append(
                    EmailMessage(
                        id=item.get("id"),
                        blob_id=item.get("blobId"),
                        thread_id=item.get("threadId") or thread_id,
                        mailbox_ids=item.get("mailboxIds", {}),
                        keywords=item.get("keywords", {}),
                        received_at=item.get("receivedAt", ""),
                        from_addr=from_list,
                        to=to_list,
                        cc=cc_list,
                        bcc=bcc_list,
                        reply_to=reply_to_list,
                        subject=item.get("subject") or "(no subject)",
                        body_text=body_text,
                        body_html=body_html if body_html else None,
                        has_attachments=len(attachments) > 0,
                        attachments=attachments,
                    )
                )

        # Sort messages chronologically by receivedAt
        ordered_messages.sort(key=lambda m: m.received_at)

        return EmailThread(
            id=thread_id,
            email_ids=email_ids,
            messages=ordered_messages,
            subject=subject,
            message_count=len(ordered_messages),
            senders=sorted(list(unique_senders)),
            has_attachments=has_attachments,
        )

    def send_email(
        self,
        to: list[str | EmailAddress],
        subject: str,
        body: str,
        from_addr: str | None = None,
        cc: list[str | EmailAddress] | None = None,
        bcc: list[str | EmailAddress] | None = None,
        draft_only: bool = False,
    ) -> dict[str, Any]:
        """Create and submit an email atomically via JMAP Email/set and EmailSubmission/set."""
        self._ensure_session()

        drafts_mb_id = self.resolve_mailbox_id("drafts") or "drafts"
        sent_mb_id = self.resolve_mailbox_id("sent") or "sent"

        target_mailbox_id = drafts_mb_id if draft_only else sent_mb_id

        # Format recipient lists
        to_entries = [_format_address(addr) for addr in to if addr]
        cc_entries = [_format_address(addr) for addr in (cc or []) if addr]
        bcc_entries = [_format_address(addr) for addr in (bcc or []) if addr]

        from_entry = [_format_address(from_addr)] if from_addr else []

        create_email_payload: dict[str, Any] = {
            "mailboxIds": {target_mailbox_id: True},
            "keywords": {"$draft": True} if draft_only else {"$seen": True},
            "subject": subject,
            "to": to_entries,
            "bodyValues": {
                "b1": {
                    "value": body,
                    "isTruncated": False,
                    "isEncodingProblem": False,
                }
            },
            "textBody": [
                {
                    "partId": "b1",
                    "type": "text/plain",
                }
            ],
        }

        if from_entry:
            create_email_payload["from"] = from_entry
        if cc_entries:
            create_email_payload["cc"] = cc_entries
        if bcc_entries:
            create_email_payload["bcc"] = bcc_entries

        # Atomic transaction: Email/set followed by EmailSubmission/set if sending
        method_calls = [
            [
                "Email/set",
                {
                    "accountId": self.account_id,
                    "create": {"k1": create_email_payload},
                },
                "c0",
            ]
        ]

        if not draft_only:
            envelope_rcpt = [e["email"] for e in (to_entries + cc_entries + bcc_entries)]
            submission_payload = {
                "emailId": "#k1",
                "envelope": {
                    "mailFrom": {"email": from_addr or ""},
                    "rcptTo": [{"email": e} for e in envelope_rcpt],
                },
            }
            method_calls.append(
                [
                    "EmailSubmission/set",
                    {
                        "accountId": self.account_id,
                        "onSuccessDestroyEmail": False,
                        "create": {"s1": submission_payload},
                    },
                    "sub0",
                ]
            )

        resp = self.request(method_calls)

        created_email_id = None
        submission_id = None

        for name, args, _ in resp.get("methodResponses", []):
            if name == "Email/set":
                created = args.get("created", {})
                if "k1" in created:
                    created_email_id = (
                        created["k1"].get("id")
                        if isinstance(created["k1"], dict)
                        else created["k1"]
                    )
                elif created:
                    first_val = next(iter(created.values()))
                    created_email_id = (
                        first_val.get("id") if isinstance(first_val, dict) else first_val
                    )
                not_created = args.get("notCreated", {})
                if "k1" in not_created:
                    err = not_created["k1"]
                    raise RuntimeError(f"Failed to create JMAP email draft: {err}")
                elif not_created:
                    raise RuntimeError(f"Failed to create JMAP email draft: {not_created}")

            elif name == "EmailSubmission/set":
                created_sub = args.get("created", {})
                if "s1" in created_sub:
                    submission_id = (
                        created_sub["s1"].get("id")
                        if isinstance(created_sub["s1"], dict)
                        else created_sub["s1"]
                    )
                elif created_sub:
                    first_val = next(iter(created_sub.values()))
                    submission_id = (
                        first_val.get("id") if isinstance(first_val, dict) else first_val
                    )
                not_created_sub = args.get("notCreated", {})
                if "s1" in not_created_sub:
                    err = not_created_sub["s1"]
                    raise RuntimeError(f"Email creation succeeded but submission failed: {err}")
                elif not_created_sub:
                    raise RuntimeError(
                        f"Email creation succeeded but submission failed: {not_created_sub}"
                    )

        return {
            "status": "draft_created" if draft_only else "sent",
            "emailId": created_email_id,
            "submissionId": submission_id,
        }


# Method aliases for convenience
JMAPClient.get_session = JMAPClient.discover_session
JMAPClient.list_mailboxes = JMAPClient.get_mailboxes
