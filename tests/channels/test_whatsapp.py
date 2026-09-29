"""Tests for the WhatsApp channel.

Cover:
- verify_signature: valid signature passes, tampered payload fails.
- handle_webhook extracts message text + phone from a sample Meta payload.
- send_message posts to the correct Cloud API endpoint (mock requests).
"""


def test_verify_signature_valid():
    raise NotImplementedError


def test_verify_signature_tampered_fails():
    raise NotImplementedError


def test_handle_webhook_extracts_message():
    raise NotImplementedError


def test_send_message_endpoint():
    raise NotImplementedError
