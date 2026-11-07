"""
Email delivery for the notification "email" channel (Phase 3).

Off by default. With no configuration the email channel stays what it has always been:
a logged row labelled "Email (simulated)", and nothing is sent. Real delivery is switched
on by setting EMAIL_PROVIDER=acs (Azure Communication Services Email, the provider chosen
in ROADMAP.md) plus two more settings:

    EMAIL_PROVIDER         "simulated" (default) or "acs"
    EMAIL_ENABLED          optional on/off switch: "false" keeps email simulated even when
                           the settings below are filled in (anything else = on)
    ACS_CONNECTION_STRING  the Communication Service's connection string (a secret --
                           an Azure app setting, never the repo)
    EMAIL_SENDER_ADDRESS   a verified sender, e.g. DoNotReply@<guid>.azurecomm.net

send_email() never raises and never returns anything but one of three outcomes, which the
notifications table stores so the page can say what actually happened:

    "simulated"  nothing was sent (the default, and what every test uses)
    "sent"       the provider accepted the message
    "failed"     the provider was asked and didn't deliver, or is misconfigured

A failed email must never break the request that triggered it -- a claim is filed and a
decision is recorded whether or not the email goes out -- so every error is caught here,
logged by type (never with a connection string or message body in the log), and reported
as "failed".

The ACS client package (azure-communication-email) is imported only when the acs provider
is actually used, so the app runs without it installed. It is pinned in requirements.txt.
"""

import logging
import os

SIMULATED = "simulated"
SENT = "sent"
FAILED = "failed"

log = logging.getLogger("uvicorn.error")


def provider() -> str:
    """The active provider. EMAIL_ENABLED=false (or 0/no/off) forces "simulated" without
    touching the other settings, so real email can be switched off and on again."""
    if os.environ.get("EMAIL_ENABLED", "").strip().lower() in ("false", "0", "no", "off"):
        return SIMULATED
    return os.environ.get("EMAIL_PROVIDER", "").strip().lower() or SIMULATED


def _send_via_acs(to: str, subject: str, body: str, html: str | None = None) -> None:
    """Send one email (plain text, plus an HTML version when given) through Azure Communication Services. Raises on any
    problem (missing setting, missing package, rejected message); send_email() turns
    that into "failed".
    """
    from azure.communication.email import EmailClient  # lazy: only needed when enabled

    client = EmailClient.from_connection_string(os.environ["ACS_CONNECTION_STRING"])
    message = {
        "senderAddress": os.environ["EMAIL_SENDER_ADDRESS"],
        "recipients": {"to": [{"address": to}]},
        "content": {"subject": subject, "plainText": body},
    }
    if html:
        message["content"]["html"] = html
    result = client.begin_send(message).result()
    status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
    if status != "Succeeded":
        raise RuntimeError(f"ACS reported status {status!r}")


def send_email(to: str, subject: str, body: str, html: str | None = None) -> str:
    """Attempt delivery per EMAIL_PROVIDER and return "simulated", "sent" or "failed"."""
    name = provider()
    if name == SIMULATED:
        return SIMULATED
    if name != "acs":
        log.warning("Unknown EMAIL_PROVIDER %r; email not sent.", name)
        return FAILED
    try:
        _send_via_acs(to, subject, body, html)
    except KeyError as exc:
        log.warning("Email not sent: setting %s is missing.", exc)
        return FAILED
    except Exception as exc:  # noqa: BLE001 -- must never break the request; logged by type only
        # Azure's HTTP status and error code (e.g. 429 / TooManyRequests) say why a message
        # was refused and carry no secrets; the message text itself is left out.
        detail = getattr(exc, "status_code", None), getattr(getattr(exc, "error", None), "code", None)
        log.warning("Email not sent: %s%s.", type(exc).__name__, f" (status {detail[0]}, code {detail[1]})" if any(detail) else "")
        return FAILED
    return SENT
