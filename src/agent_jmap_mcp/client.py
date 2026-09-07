"""RFC 8620 and RFC 8621 compliant JMAP Client for modern email automation."""

import email.message
import email.policy
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agent_jmap_mcp.models import EmailAddress, EmailHeader, EmailMessage, MailboxInfo


def _format_address(addr: Any) -> Dict[str, str]:
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
        token: Optional[str] = None,
        api_token: Optional[str] = None,
        account_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.session_url = session_url.rstrip("/")
        auth_tok = token or api_token or ""
        self.token = auth_tok.strip()
        self.api_token = self.token
        self.account_id = account_id
        self.timeout = timeout

        self._api_url: Optional[str] = None
        self._download_url: Optional[str] = None
        self._upload_url: Optional[str] = None
        self._primary_accounts: Dict[str, str] = {}
        self._session_initialized = False

    @property
    def primary_mail_account_id(self) -> Optional[str]:
        return self.account_id

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def discover_session(self) -> Dict[str, Any]:
        """Fetch JMAP session resource (RFC 8620 Section 2)."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self.session_url, headers=self._headers())
            if resp.status_code == 401:
                raise PermissionError("JMAP Authentication failed: Invalid or expired Bearer token.")
            resp.raise_for_status()
            data = resp.json()

        self._api_url = data.get("apiUrl")
        self._download_url = data.get("downloadUrl")
        self._upload_url = data.get("uploadUrl")
        self._primary_accounts = data.get("primaryAccounts", {})

        if not self.account_id:
            self.account_id = (
                self._primary_accounts.get(self.CAPABILITY_MAIL)
                or self._primary_accounts.get(self.CAPABILITY_CORE)
                or next(iter(data.get("accounts", {}).keys()), None)
            )

        if not self.account_id:
            raise ValueError("No JMAP Mail account ID could be determined from the session.")

        self._session_initialized = True
        return data

    def _ensure_session(self) -> None:
        if not self._session_initialized or not self._api_url:
            self.discover_session()

    def request(self, method_calls: List[List[Any]]) -> Dict[str, Any]:
        """Execute a standard JMAP Request containing one or more method calls."""
        self._ensure_session()

        payload = {
            "using": [self.CAPABILITY_CORE, self.CAPABILITY_MAIL, self.CAPABILITY_SUBMISSION],
            "methodCalls": method_calls,
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._api_url, headers=self._headers(), json=payload)
            if resp.status_code == 401:
                raise PermissionError("JMAP API Request unauthorized: Invalid token.")
            resp.raise_for_status()
            return resp.json()

    def get_mailboxes(self) -> List[MailboxInfo]:
        """Retrieve all available mailboxes and folders."""
        self._ensure_session()
        response = self.request([["Mailbox/get", {"accountId": self.account_id}, "m0"]])
        method_responses = response.get("methodResponses", [])

        mailboxes: List[MailboxInfo] = []
        for name, args, call_id in method_responses:
            if name == "Mailbox/get":
                for item in args.get("list", []):
                    mailboxes.append(
                        MailboxInfo(
                            id=item.get("id"),
                            name=item.get("name"),
                            role=item.get("role"),
                            totalEmails=item.get("totalEmails", 0),
                            unreadEmails=item.get("unreadEmails", 0),
                        )
                    )
        return mailboxes

    def resolve_mailbox_id(self, mailbox_name_or_role: str) -> Optional[str]:
        """Find a mailbox ID by its role or case-insensitive name."""
        mailboxes = self.get_mailboxes()
        target = mailbox_name_or_role.lower().strip()

        for mb in mailboxes:
            if mb.role and mb.role.lower() == target:
                return mb.id
        for mb in mailboxes:
            if mb.name.lower() == target:
                return mb.id
            if target == "inbox" and (mb.role == "inbox" or mb.name.upper() == "INBOX"):
                return mb.id
        return None

    def list_emails(
        self,
        mailbox_name: str = "INBOX",
        limit: int = 10,
        unread_only: bool = False,
        query_text: Optional[str] = None,
    ) -> List[EmailHeader]:
        """Query and list email headers with preview."""
        self._ensure_session()
        mailbox_id = self.resolve_mailbox_id(mailbox_name)

        filter_conditions: Dict[str, Any] = {}
        if mailbox_id:
            filter_conditions["inMailbox"] = mailbox_id
        if unread_only:
            filter_conditions["hasKeyword"] = False
            filter_conditions["keyword"] = "$seen"
        if query_text:
            filter_conditions["text"] = query_text

        query_args: Dict[str, Any] = {
            "accountId": self.account_id,
            "filter": filter_conditions if filter_conditions else None,
            "sort": [{"property": "receivedAt", "isAscending": False}],
            "limit": limit,
        }
        query_args = {k: v for k, v in query_args.items() if v is not None}

        # Step 1: Query IDs
        query_resp = self.request([["Email/query", query_args, "q0"]])
        email_ids = []
        for name, args, _ in query_resp.get("methodResponses", []):
            if name == "Email/query":
                email_ids = args.get("ids", [])

        if not email_ids:
            return []

        # Step 2: Fetch headers and preview
        get_args = {
            "accountId": self.account_id,
            "ids": email_ids,
            "properties": [
                "id", "blobId", "threadId", "mailboxIds", "keywords",
                "receivedAt", "from", "to", "subject", "preview"
            ],
        }

        get_resp = self.request([["Email/get", get_args, "g0"]])
        headers: List[EmailHeader] = []

        for name, args, _ in get_resp.get("methodResponses", []):
            if name == "Email/get":
                for item in args.get("list", []):
                    keywords = item.get("keywords") or {}
                    is_unread = "$seen" not in keywords

                    from_list = [
                        EmailAddress(name=addr.get("name"), email=addr.get("email", ""))
                        for addr in (item.get("from") or [])
                    ]
                    to_list = [
                        EmailAddress(name=addr.get("name"), email=addr.get("email", ""))
                        for addr in (item.get("to") or [])
                    ]

                    headers.append(
                        EmailHeader(
                            id=item.get("id"),
                            blobId=item.get("blobId"),
                            threadId=item.get("threadId"),
                            subject=item.get("subject") or "(no subject)",
                            from_addr=from_list,
                            to=to_list,
                            receivedAt=item.get("receivedAt", ""),
                            preview=item.get("preview", ""),
                            unread=is_unread,
                            keywords=keywords,
                        )
                    )
        return headers

    def get_email(self, email_id: str, mark_as_read: bool = False) -> Optional[EmailMessage]:
        """Retrieve complete email content by ID."""
        self._ensure_session()

        get_args = {
            "accountId": self.account_id,
            "ids": [email_id],
            "properties": [
                "id", "blobId", "threadId", "mailboxIds", "keywords", "size",
                "receivedAt", "from", "to", "cc", "bcc", "replyTo", "subject",
                "bodyValues", "textBody", "htmlBody", "attachments", "preview"
            ],
            "bodyProperties": ["partId", "blobId", "size", "type", "subparts"],
            "fetchTextBodyValues": True,
            "fetchHTMLBodyValues": True,
        }

        calls = [["Email/get", get_args, "g0"]]
        if mark_as_read:
            calls.append([
                "Email/set",
                {
                    "accountId": self.account_id,
                    "update": {email_id: {"keywords/$seen": True}},
                },
                "s0",
            ])

        response = self.request(calls)
        email_data = None

        for name, args, _ in response.get("methodResponses", []):
            if name == "Email/get":
                item_list = args.get("list", [])
                if item_list:
                    email_data = item_list[0]

        if not email_data:
            return None

        # Resolve plain text body from bodyValues
        body_values = email_data.get("bodyValues", {})
        extracted_text = ""

        # 1. Try textBody parts
        for part in email_data.get("textBody", []):
            part_id = part.get("partId")
            if part_id in body_values:
                extracted_text += body_values[part_id].get("value", "")

        # 2. Fallback to htmlBody parts if plain text is empty
        extracted_html = ""
        for part in email_data.get("htmlBody", []):
            part_id = part.get("partId")
            if part_id in body_values:
                extracted_html += body_values[part_id].get("value", "")

        if not extracted_text and extracted_html:
            # Simple text extraction from HTML
            clean_text = re.sub(r"<[^>]+>", " ", extracted_html)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            extracted_text = clean_text

        from_list = [EmailAddress(name=a.get("name"), email=a.get("email", "")) for a in (email_data.get("from") or [])]
        to_list = [EmailAddress(name=a.get("name"), email=a.get("email", "")) for a in (email_data.get("to") or [])]
        cc_list = [EmailAddress(name=a.get("name"), email=a.get("email", "")) for a in (email_data.get("cc") or [])]
        bcc_list = [EmailAddress(name=a.get("name"), email=a.get("email", "")) for a in (email_data.get("bcc") or [])]
        reply_to_list = [EmailAddress(name=a.get("name"), email=a.get("email", "")) for a in (email_data.get("replyTo") or [])]

        attachments = email_data.get("attachments") or []

        return EmailMessage(
            id=email_data.get("id"),
            blobId=email_data.get("blobId"),
            threadId=email_data.get("threadId"),
            mailboxIds=email_data.get("mailboxIds", {}),
            keywords=email_data.get("keywords", {}),
            receivedAt=email_data.get("receivedAt", ""),
            from_addr=from_list,
            to=to_list,
            cc=cc_list,
            bcc=bcc_list,
            replyTo=reply_to_list,
            subject=email_data.get("subject") or "(no subject)",
            body_text=extracted_text,
            body_html=extracted_html if extracted_html else None,
            has_attachments=len(attachments) > 0,
            attachments=attachments,
        )

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        from_addr: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        draft_only: bool = False,
    ) -> Dict[str, Any]:
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

        create_email_payload: Dict[str, Any] = {
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
                    created_email_id = created["k1"].get("id") if isinstance(created["k1"], dict) else created["k1"]
                elif created:
                    first_val = next(iter(created.values()))
                    created_email_id = first_val.get("id") if isinstance(first_val, dict) else first_val
                not_created = args.get("notCreated", {})
                if "k1" in not_created:
                    err = not_created["k1"]
                    raise RuntimeError(f"Failed to create JMAP email draft: {err}")
                elif not_created:
                    raise RuntimeError(f"Failed to create JMAP email draft: {not_created}")

            elif name == "EmailSubmission/set":
                created_sub = args.get("created", {})
                if "s1" in created_sub:
                    submission_id = created_sub["s1"].get("id") if isinstance(created_sub["s1"], dict) else created_sub["s1"]
                elif created_sub:
                    first_val = next(iter(created_sub.values()))
                    submission_id = first_val.get("id") if isinstance(first_val, dict) else first_val
                not_created_sub = args.get("notCreated", {})
                if "s1" in not_created_sub:
                    err = not_created_sub["s1"]
                    raise RuntimeError(f"Email creation succeeded but submission failed: {err}")
                elif not_created_sub:
                    raise RuntimeError(f"Email creation succeeded but submission failed: {not_created_sub}")

        return {
            "status": "draft_created" if draft_only else "sent",
            "emailId": created_email_id,
            "submissionId": submission_id,
            "to": to,
            "subject": subject,
        }


# Method aliases for convenience
JMAPClient.get_session = JMAPClient.discover_session
JMAPClient.list_mailboxes = JMAPClient.get_mailboxes
