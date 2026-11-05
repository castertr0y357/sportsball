import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_discord_notification(webhook_url: str, title: str, description: str, fields: list = None, color: int = 0x1e3a8a):
    """
    Send a rich embed message to a Discord channel via webhook.
    Fails silently with a logged warning if network or webhook is invalid.
    """
    if not webhook_url:
        return False

    payload = {
        "username": "SportsBall Bot",
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "fields": fields or [],
                "footer": {
                    "text": "SportsBall — Rec League Hub"
                }
            }
        ]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=4)
        return resp.status_code in (200, 204)
    except Exception as e:
        logger.warning(f"Failed to deliver Discord webhook: {e}")
        return False


def send_twilio_sms(to_phone: str, body: str):
    """
    Optional Twilio SMS sender.
    Gracefully skips if credentials are not configured in settings.
    """
    sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '')

    if not (sid and token and from_number and to_phone):
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = {
        'From': from_number,
        'To': to_phone,
        'Body': f"[SportsBall] {body}"
    }

    try:
        resp = requests.post(url, data=data, auth=(sid, token), timeout=5)
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.warning(f"Failed to deliver SMS to {to_phone}: {e}")
        return False
