"""WhatsApp Cloud API — webhook handler + outbound messages.

- handle_webhook(req) -> dict:
    Parse incoming Meta webhook payload (user-initiated messages only).
    Returns the extracted user message + phone number for the /chat endpoint.
- verify_signature(req) -> bool:
    Verify X-Hub-Signature-256 using the app secret — confirms the call is
    genuinely from Meta.
- send_message(to_phone, text) -> None:
    Outbound reply via the WhatsApp Cloud API.
"""


def handle_webhook(req) -> dict:
    raise NotImplementedError


def verify_signature(req) -> bool:
    raise NotImplementedError


def send_message(to_phone: str, text: str) -> None:
    raise NotImplementedError
