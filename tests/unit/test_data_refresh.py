from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nautilus_lab.application.data_refresh import plan_targets, summarize, symbol_of

NOW = datetime(2026, 10, 4, 1, 30, tzinfo=UTC)


def _report(status: str, days_ago: float) -> dict[str, object]:
    return {"status": status, "last": (NOW - timedelta(days=days_ago)).isoformat()}


def test_symbol_of_strips_venue_slash_and_perp() -> None:
    assert symbol_of("BTC/USDT.SIM") == "BTCUSDT"
    assert symbol_of("BTCUSDT-PERP.SIM") == "BTCUSDT"
    assert symbol_of("BTCUSDT.SIM") == "BTCUSDT"


def test_only_archive_named_catalogs_are_planned() -> None:
    targets = plan_targets(
        {
            "catalog_spot_1d": ["BTC/USDT.SIM", "ETH/USDT.SIM", "BTCUSDT.SIM"],
            "catalog_perp_4h": ["SOLUSDT-PERP.SIM"],
            "catalog_2019_4h": ["BTC/USDT.SIM"],  # hand-made: not refreshed
            "catalog_spot_1d_old": ["BTC/USDT.SIM"],
            "catalog_perp_1d": [],  # empty: nothing to refresh
        }
    )
    assert [(t.catalog, t.market, t.interval, t.symbols) for t in targets] == [
        ("catalog_perp_4h", "um", "4h", ("SOLUSDT",)),
        ("catalog_spot_1d", "spot", "1d", ("BTCUSDT", "ETHUSDT")),
    ]


def test_summary_counts_fail_and_separates_stale_from_delisted() -> None:
    summary = summarize(
        {
            "catalog_spot_1d": {
                "BTC-1d": _report("ok", 1),
                "ETH-1d": _report("warn", 1),
                "LUNA-1d": _report("fail", 1),
                "SOL-1d": _report("ok", 5),  # should have moved: stale
                "WAVES-1d": _report("ok", 400),  # delisted long ago: not stale
            }
        },
        now=NOW,
    )
    assert (summary.total, summary.ok, summary.warn) == (5, 3, 1)
    assert [item.bar_type for item in summary.fail] == ["LUNA-1d"]
    assert [item.bar_type for item in summary.stale] == ["SOL-1d"]
    assert not summary.healthy
    message = summary.message()
    assert message.startswith("data refresh: 5 series, ok 3, warn 1, fail 1, stale 1")
    assert "FAIL catalog_spot_1d/LUNA-1d" in message
    assert "STALE catalog_spot_1d/SOL-1d" in message


def test_a_clean_night_is_healthy_unless_an_ingest_step_failed() -> None:
    reports = {"catalog_spot_1d": {"BTC-1d": _report("ok", 1)}}
    assert summarize(reports, now=NOW).healthy
    assert not summarize(reports, now=NOW, ingest_failures=1).healthy


def test_long_lists_are_cut_in_the_message() -> None:
    reports = {"c": {f"S{i}": _report("fail", 1) for i in range(12)}}
    message = summarize(reports, now=NOW).message(max_listed=3)
    assert message.count("FAIL c/") == 3
    assert "and 9 more fail" in message
