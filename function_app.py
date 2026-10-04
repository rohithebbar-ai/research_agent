"""Azure Functions entry point — all triggers registered here (v2 programming model).

Triggers:
- /chat (HTTP): single endpoint used by both WhatsApp webhook and the website widget.
  Resolves canonical user_id (via channels.auth), then runs the Summarizer agent loop.
- /scout/on-demand (HTTP): on-demand A2A entry point — Summarizer's fetch_more()
  calls this to trigger a concept-based Scout run mid-conversation.
- scout_daily (Timer): unattended daily category-based paper ingestion.
"""

import azure.functions as func


def chat_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger: /chat — WhatsApp webhook + website widget.

    1. Authenticate (Entra ID token for web, X-Hub-Signature-256 + phone
       allow-list for WhatsApp) -> canonical user_id.
    2. Run Summarizer agent loop (agents.summarizer).
    3. Return grounded, cited answer.
    """
    raise NotImplementedError


def scout_on_demand(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger: /scout/on-demand — called by Summarizer's fetch_more tool.

    Body: {"concept": str, "reason": str}
    Runs a concept-based Scout pass, returns count of newly indexed papers.
    """
    raise NotImplementedError


def scout_daily(timer: func.TimerRequest) -> None:
    """Timer trigger: daily at a fixed UTC time.

    Runs the category-based Scout agent loop (agents.paper_scout) and logs a run
    summary (papers seen, papers indexed) to Application Insights.
    """
    raise NotImplementedError
