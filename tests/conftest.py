"""Pytest fixtures and mock responses for JMAP Client & Server testing."""

import pytest


@pytest.fixture
def mock_session_response():
    return {
        "username": "user@example.com",
        "apiUrl": "https://jmap.example.com/api",
        "downloadUrl": "https://jmap.example.com/download/{accountId}/{blobId}/{name}",
        "uploadUrl": "https://jmap.example.com/upload/{accountId}",
        "eventSourceUrl": "https://jmap.example.com/eventsource",
        "primaryAccounts": {
            "urn:ietf:params:jmap:core": "acc_123",
            "urn:ietf:params:jmap:mail": "acc_123",
            "urn:ietf:params:jmap:submission": "acc_123",
        },
        "accounts": {
            "acc_123": {
                "name": "user@example.com",
                "isPersonal": True,
                "isReadOnly": False,
                "accountCapabilities": {
                    "urn:ietf:params:jmap:core": {},
                    "urn:ietf:params:jmap:mail": {},
                    "urn:ietf:params:jmap:submission": {},
                },
            }
        },
        "capabilities": {
            "urn:ietf:params:jmap:core": {},
            "urn:ietf:params:jmap:mail": {},
            "urn:ietf:params:jmap:submission": {},
        },
    }
