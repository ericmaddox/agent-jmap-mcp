"""Unit tests for JMAPClient."""

import httpx
import pytest
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
