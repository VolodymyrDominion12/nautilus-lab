from unittest.mock import MagicMock, patch

from nautilus_lab.infrastructure.alerts import (
    CompositeAlertNotifier,
    NullAlertNotifier,
    TelegramAlertNotifier,
    WebhookAlertNotifier,
    build_notifier,
)


def test_null_notifier_always_returns_true() -> None:
    notifier = NullAlertNotifier()
    assert notifier.notify("test message") is True


def test_telegram_notifier_success() -> None:
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = TelegramAlertNotifier(bot_token="token123", chat_id="chat456")
        assert notifier.notify("hello telegram") is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "token123" in args[0]
        assert kwargs["json"]["chat_id"] == "chat456"


def test_telegram_notifier_failure_status_handled_safely() -> None:
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
        notifier = TelegramAlertNotifier(bot_token="token123", chat_id="chat456")
        assert notifier.notify("hello telegram") is False


def test_telegram_notifier_exception_handled_safely() -> None:
    with patch("httpx.post", side_effect=RuntimeError("connection error")):
        notifier = TelegramAlertNotifier(bot_token="token123", chat_id="chat456")
        assert notifier.notify("hello telegram") is False


def test_webhook_notifier_success() -> None:
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = WebhookAlertNotifier(webhook_url="https://hooks.example.com/alert")
        assert notifier.notify("webhook event", level="WARNING") is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://hooks.example.com/alert"
        assert "[WARNING]" in kwargs["json"]["text"]


def test_webhook_notifier_error_handled_safely() -> None:
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
        notifier = WebhookAlertNotifier(webhook_url="https://hooks.example.com/alert")
        assert notifier.notify("webhook event") is False


def test_build_notifier_factory() -> None:
    assert isinstance(build_notifier(), NullAlertNotifier)

    tg = build_notifier(telegram_token="token", telegram_chat_id="chat")
    assert isinstance(tg, TelegramAlertNotifier)

    wh = build_notifier(webhook_url="https://hooks.example.com")
    assert isinstance(wh, WebhookAlertNotifier)

    comp = build_notifier(
        telegram_token="token",
        telegram_chat_id="chat",
        webhook_url="https://hooks.example.com",
    )
    assert isinstance(comp, CompositeAlertNotifier)
