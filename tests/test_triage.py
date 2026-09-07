"""Unit tests for triage and classification rules."""

from agent_jmap_mcp.triage import classify_email


def test_classify_urgent():
    cat, prio, _ = classify_email(
        subject="Urgent: Security Alert - 2FA code",
        sender="security@auth.com",
        preview="Your single use verification code is 123456.",
    )
    assert cat == "urgent"
    assert prio == 1


def test_classify_action_needed():
    cat, prio, _ = classify_email(
        subject="Invoice #4928 Due for Payment",
        sender="billing@saas.com",
        preview="Please review the attached invoice due on Friday.",
    )
    assert cat == "action_needed"
    assert prio == 2


def test_classify_newsletter():
    cat, prio, _ = classify_email(
        subject="Weekly AI Digest Issue #42",
        sender="newsletter@weeklydigest.com",
        preview="Click here to unsubscribe if you no longer wish to receive this.",
    )
    assert cat == "newsletter"
    assert prio == 5
