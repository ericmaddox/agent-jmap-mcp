"""Unit tests for JMAPClient."""

import httpx

from agent_jmap_mcp.client import JMAPClient
from agent_jmap_mcp.models import EmailAddress

MOCK_SESSION = {
    "apiUrl": "https://jmap.example.com/api/",
    "downloadUrl": "https://jmap.example.com/download/{accountId}/{blobId}/{name}",
    "uploadUrl": "https://jmap.example.com/upload/{accountId}/",
    "primaryAccounts": {
        "urn:ietf:params:jmap:mail": "acc-123",
        "urn:ietf:params:jmap:submission": "acc-123",
    },
    "accounts": {
        "acc-123": {
            "name": "user@example.com",
            "isPersonal": True,
            "isReadOnly": False,
            "accountCapabilities": {
                "urn:ietf:params:jmap:mail": {},
                "urn:ietf:params:jmap:submission": {},
            },
        }
    },
}


def test_client_initialization():
    client = JMAPClient(
        session_url="https://jmap.example.com/.well-known/jmap",
        api_token="test-token-123",
    )
    assert client.session_url == "https://jmap.example.com/.well-known/jmap"
    assert client.api_token == "test-token-123"


def test_session_fetch(monkeypatch):
    client = JMAPClient(
        session_url="https://jmap.example.com/.well-known/jmap",
        api_token="test-token-123",
    )

    def mock_get(self, url, **kwargs):
        return httpx.Response(200, json=MOCK_SESSION, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    session = client.get_session()
    assert session["apiUrl"] == "https://jmap.example.com/api/"
    assert client.primary_mail_account_id == "acc-123"


def test_list_mailboxes(monkeypatch):
    client = JMAPClient(
        session_url="https://jmap.example.com/.well-known/jmap",
        api_token="test-token-123",
    )

    def mock_get(self, url, **kwargs):
        return httpx.Response(200, json=MOCK_SESSION, request=httpx.Request("GET", url))

    def mock_post(self, url, **kwargs):
        data = {
            "methodResponses": [
                [
                    "Mailbox/get",
                    {
                        "accountId": "acc-123",
                        "state": "s1",
                        "list": [
                            {
                                "id": "mb-inbox",
                                "name": "Inbox",
                                "role": "inbox",
                                "totalEmails": 42,
                                "unreadEmails": 3,
                            },
                            {
                                "id": "mb-sent",
                                "name": "Sent",
                                "role": "sent",
                                "totalEmails": 15,
                                "unreadEmails": 0,
                            },
                        ],
                    },
                    "0",
                ]
            ]
        }
        return httpx.Response(200, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    monkeypatch.setattr(httpx.Client, "post", mock_post)

    mailboxes = client.list_mailboxes()
    assert len(mailboxes) == 2
    assert mailboxes[0].name == "Inbox"
    assert mailboxes[0].role == "inbox"
    assert mailboxes[0].total_emails == 42
    assert mailboxes[0].unread_emails == 3


def test_html_to_markdown_body_extraction(monkeypatch):
    client = JMAPClient(
        session_url="https://jmap.example.com/.well-known/jmap",
        api_token="test-token-123",
    )

    def mock_get(self, url, **kwargs):
        return httpx.Response(200, json=MOCK_SESSION, request=httpx.Request("GET", url))

    def mock_post(self, url, **kwargs):
        data = {
            "methodResponses": [
                [
                    "Email/get",
                    {
                        "accountId": "acc-123",
                        "list": [
                            {
                                "id": "msg-html-only",
                                "blobId": "b1",
                                "threadId": "t1",
                                "receivedAt": "2026-09-06T12:00:00Z",
                                "subject": "HTML Newsletter",
                                "htmlBody": [{"partId": "h1"}],
                                "bodyValues": {
                                    "h1": {
                                        "value": "<h1>Welcome</h1><p>Check out our <strong>new features</strong>!</p>"
                                    }
                                },
                                "attachments": [],
                            }
                        ],
                    },
                    "0",
                ]
            ]
        }
        return httpx.Response(200, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    monkeypatch.setattr(httpx.Client, "post", mock_post)

    email = client.get_email("msg-html-only")
    assert email is not None
    assert "# Welcome" in email.body_text
    assert "**new features**" in email.body_text


def test_download_attachment(monkeypatch, tmp_path):
    client = JMAPClient(
        session_url="https://jmap.example.com/.well-known/jmap",
        api_token="test-token-123",
    )

    def mock_get(self, url, **kwargs):
        if ".well-known/jmap" in str(url):
            return httpx.Response(200, json=MOCK_SESSION, request=httpx.Request("GET", url))
        if "download" in str(url):
            return httpx.Response(
                200, content=b"%PDF-1.4 mock binary data", request=httpx.Request("GET", url)
            )
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    out_file = tmp_path / "sample.pdf"
    content = client.download_attachment(
        blob_id="blob-999", filename="sample.pdf", output_path=str(out_file)
    )

    assert content == b"%PDF-1.4 mock binary data"
    assert out_file.exists()
    assert out_file.read_bytes() == b"%PDF-1.4 mock binary data"


def test_get_thread(monkeypatch):
    client = JMAPClient(
        session_url="https://jmap.example.com/.well-known/jmap",
        api_token="test-token-123",
    )

    def mock_get(self, url, **kwargs):
        return httpx.Response(200, json=MOCK_SESSION, request=httpx.Request("GET", url))

    def mock_post(self, url, **kwargs):
        data = {
            "methodResponses": [
                [
                    "Thread/get",
                    {
                        "accountId": "acc-123",
                        "list": [
                            {
                                "id": "thread-abc",
                                "emailIds": ["m1", "m2"],
                            }
                        ],
                    },
                    "t0",
                ],
                [
                    "Email/get",
                    {
                        "accountId": "acc-123",
                        "list": [
                            {
                                "id": "m1",
                                "threadId": "thread-abc",
                                "subject": "Project Proposal",
                                "from": [{"name": "Alice", "email": "alice@example.com"}],
                                "to": [{"name": "Bob", "email": "bob@example.com"}],
                                "receivedAt": "2026-09-06T10:00:00Z",
                                "textBody": [{"partId": "p1"}],
                                "bodyValues": {"p1": {"value": "Initial proposal notes."}},
                            },
                            {
                                "id": "m2",
                                "threadId": "thread-abc",
                                "subject": "Re: Project Proposal",
                                "from": [{"name": "Bob", "email": "bob@example.com"}],
                                "to": [{"name": "Alice", "email": "alice@example.com"}],
                                "receivedAt": "2026-09-06T10:30:00Z",
                                "textBody": [{"partId": "p2"}],
                                "bodyValues": {"p2": {"value": "Looks great, approved!"}},
                            },
                        ],
                    },
                    "e0",
                ],
            ]
        }
        return httpx.Response(200, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    monkeypatch.setattr(httpx.Client, "post", mock_post)

    thread = client.get_thread("thread-abc")
    assert thread is not None
    assert thread.id == "thread-abc"
    assert thread.message_count == 2
    assert thread.email_ids == ["m1", "m2"]
    assert len(thread.messages) == 2
    assert thread.messages[0].id == "m1"
    assert thread.messages[1].id == "m2"
    assert "Initial proposal notes." in thread.messages[0].body_text
    assert "Looks great, approved!" in thread.messages[1].body_text


def test_atomic_send_email(monkeypatch):
    client = JMAPClient(
        session_url="https://jmap.example.com/.well-known/jmap",
        api_token="test-token-123",
    )

    def mock_get(self, url, **kwargs):
        return httpx.Response(200, json=MOCK_SESSION, request=httpx.Request("GET", url))

    def mock_post(self, url, **kwargs):
        data = {
            "methodResponses": [
                [
                    "Email/set",
                    {
                        "accountId": "acc-123",
                        "created": {"draft1": {"id": "msg-new-999"}},
                    },
                    "c1",
                ],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": "acc-123",
                        "created": {"sub1": {"id": "sub-999"}},
                    },
                    "c2",
                ],
            ]
        }
        return httpx.Response(200, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    monkeypatch.setattr(httpx.Client, "post", mock_post)

    to_addr = [EmailAddress(name="Alice", email="alice@example.com")]
    res = client.send_email(
        to=to_addr,
        subject="Test Atomic Message",
        body="Hello JMAP!",
    )
    assert res["emailId"] == "msg-new-999"
    assert res["submissionId"] == "sub-999"
