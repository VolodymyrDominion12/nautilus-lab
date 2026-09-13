from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class AlertNotifier(Protocol):
    """Notification port for risk events, circuit breaker triggers, and run completions."""

    def notify(self, message: str, level: str = "INFO") -> bool: ...


class NullAlertNotifier:
    """Default no-op notifier."""

    def notify(self, message: str, level: str = "INFO") -> bool:
        return True


class TelegramAlertNotifier:
    """Sends messages to a Telegram chat via Bot API (fail-safe)."""

    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: float = 5.0) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout_seconds

    def notify(self, message: str, level: str = "INFO") -> bool:
        try:
            import httpx

            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            payload = {
                "chat_id": self._chat_id,
                "text": f"[{level}] nautilus-lab: {message}",
            }
            resp = httpx.post(url, json=payload, timeout=self._timeout)
            if resp.status_code == 200:
                return True
            logger.warning(
                "Telegram notification failed with HTTP %d: %s",
                resp.status_code,
                resp.text,
            )
            return False
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)
            return False


class WebhookAlertNotifier:
    """Sends JSON alerts to generic webhooks (Slack, Discord, custom endpoints)."""

    def __init__(self, webhook_url: str, timeout_seconds: float = 5.0) -> None:
        self._url = webhook_url
        self._timeout = timeout_seconds

    def notify(self, message: str, level: str = "INFO") -> bool:
        try:
            import httpx

            # Generic payload with 'text' and 'content' for Slack/Discord compatibility
            payload = {
                "text": f"[{level}] {message}",
                "content": f"[{level}] {message}",
                "level": level,
            }
            resp = httpx.post(self._url, json=payload, timeout=self._timeout)
            if 200 <= resp.status_code < 300:
                return True
            logger.warning(
                "Webhook notification failed with HTTP %d: %s",
                resp.status_code,
                resp.text,
            )
            return False
        except Exception as exc:
            logger.warning("Webhook notification failed: %s", exc)
            return False


class CompositeAlertNotifier:
    """Dispatches alerts across multiple configured notifiers."""

    def __init__(self, notifiers: list[AlertNotifier]) -> None:
        self._notifiers = notifiers

    def notify(self, message: str, level: str = "INFO") -> bool:
        all_succeeded = True
        for notifier in self._notifiers:
            if not notifier.notify(message, level=level):
                all_succeeded = False
        return all_succeeded


def build_notifier(
    *,
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
    webhook_url: str | None = None,
) -> AlertNotifier:
    """Factory creating appropriate notifier based on provided configuration."""
    notifiers: list[AlertNotifier] = []
    if telegram_token and telegram_chat_id:
        notifiers.append(TelegramAlertNotifier(telegram_token, telegram_chat_id))
    if webhook_url:
        notifiers.append(WebhookAlertNotifier(webhook_url))
    if not notifiers:
        return NullAlertNotifier()
    if len(notifiers) == 1:
        return notifiers[0]
    return CompositeAlertNotifier(notifiers)
