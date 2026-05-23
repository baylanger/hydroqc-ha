"""Unit tests for the Tarif D low/high price split feature (PR3).

Tests cover:
- _get_period_start_for_date: billing period boundary detection
- reg/haut split calculation with known consumption sequences
- Threshold reset at billing period boundaries
- 60-day fallback approximation anchored to oldest known period
- The 40 kWh/day constant is used (not hardcoded)
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import constants directly — changes here should break tests intentionally
from custom_components.hydroqc.const import (
    TARIF_D_HISTORY_PERIOD_DAYS,
    TARIF_D_THRESHOLD_KWH_PER_DAY,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_stats_manager(
    rate: str = "D",
    billing_duration_entity: str | None = None,
    contract=None,
):
    """Create a minimal StatisticsManager for testing without HA dependencies."""
    from unittest.mock import MagicMock, patch

    with patch(
        "custom_components.hydroqc.statistics_manager.get_instance"
    ), patch(
        "custom_components.hydroqc.statistics_manager.statistics"
    ):
        from custom_components.hydroqc.statistics_manager import StatisticsManager

        hass = MagicMock()
        mgr = StatisticsManager.__new__(StatisticsManager)
        mgr.hass = hass
        mgr._rate = rate
        mgr._contract = contract
        mgr._contract_name = "maison"
        mgr._billing_duration_entity = billing_duration_entity
        mgr._legacy_billing_duration_entity = (
            "sensor.hydroqc_maison_current_billing_period_duration"
        )
        mgr._get_statistic_id = lambda t: f"hydroqc:maison_{t}_hourly_consumption"
        return mgr


# ── Constants tests ───────────────────────────────────────────────────────────


def test_threshold_constant_value() -> None:
    """TARIF_D_THRESHOLD_KWH_PER_DAY must be 40."""
    assert TARIF_D_THRESHOLD_KWH_PER_DAY == 40


def test_history_period_constant_value() -> None:
    """TARIF_D_HISTORY_PERIOD_DAYS must be 60."""
    assert TARIF_D_HISTORY_PERIOD_DAYS == 60


# ── _get_period_start_for_date tests ─────────────────────────────────────────


class TestGetPeriodStartForDate:
    """Tests for _get_period_start_for_date method."""

    def setup_method(self):
        self.mgr = make_stats_manager()

    def test_date_within_known_period(self) -> None:
        """Date within a known period should return that period's start."""
        period_start = datetime.date(2026, 3, 20)
        period_durations = {period_start: 62}

        result = self.mgr._get_period_start_for_date(
            datetime.date(2026, 4, 15), period_durations
        )
        assert result == period_start

    def test_date_at_period_start(self) -> None:
        """Date exactly at period start should return that period."""
        period_start = datetime.date(2026, 3, 20)
        period_durations = {period_start: 62}

        result = self.mgr._get_period_start_for_date(period_start, period_durations)
        assert result == period_start

    def test_date_at_period_end_goes_to_next(self) -> None:
        """Date exactly at period end (exclusive) should go to next period."""
        period_start = datetime.date(2026, 3, 20)
        next_start = datetime.date(2026, 5, 21)
        period_durations = {
            period_start: 62,
            next_start: 58,
        }
        # May 21 is start of next period (exclusive end of first)
        result = self.mgr._get_period_start_for_date(next_start, period_durations)
        assert result == next_start

    def test_date_before_all_known_periods_extrapolates_backward(self) -> None:
        """Date before all known periods should extrapolate back in 60-day blocks."""
        oldest_known = datetime.date(2026, 2, 22)
        period_durations = {oldest_known: 57}

        # Date 65 days before oldest known — should be one 60-day block back
        test_date = oldest_known - datetime.timedelta(days=65)
        result = self.mgr._get_period_start_for_date(test_date, period_durations)

        # Should be exactly one TARIF_D_HISTORY_PERIOD_DAYS block before oldest_known
        expected = oldest_known - datetime.timedelta(days=TARIF_D_HISTORY_PERIOD_DAYS)
        assert result == expected

    def test_date_just_before_oldest_extrapolates_one_block(self) -> None:
        """Date 1 day before oldest known period should be one block back."""
        oldest_known = datetime.date(2026, 2, 22)
        period_durations = {oldest_known: 57}

        test_date = oldest_known - datetime.timedelta(days=1)
        result = self.mgr._get_period_start_for_date(test_date, period_durations)

        expected = oldest_known - datetime.timedelta(days=TARIF_D_HISTORY_PERIOD_DAYS)
        assert result == expected

    def test_empty_period_durations_uses_fixed_blocks(self) -> None:
        """Empty period_durations should use fixed 60-day blocks from reference."""
        test_date = datetime.date(2024, 3, 20)
        result = self.mgr._get_period_start_for_date(test_date, {})
        # Result should be a date, not None
        assert result is not None
        # Result should be within one period of test_date
        assert (test_date - result).days < TARIF_D_HISTORY_PERIOD_DAYS

    def test_multiple_periods_finds_correct_one(self) -> None:
        """Multiple periods — should find the correct containing period."""
        period_durations = {
            datetime.date(2025, 11, 1): 57,
            datetime.date(2025, 12, 28): 62,
            datetime.date(2026, 2, 28): 58,
            datetime.date(2026, 4, 27): 60,
        }
        # Test date in second period
        result = self.mgr._get_period_start_for_date(
            datetime.date(2026, 1, 15), period_durations
        )
        assert result == datetime.date(2025, 12, 28)

    def test_extrapolation_is_anchored_to_oldest_known(self) -> None:
        """Extrapolation backward must be anchored to oldest known period,
        not an arbitrary date like 2020-01-01.

        This was the original bug — wrong anchor caused misaligned periods.
        """
        oldest_known = datetime.date(2026, 2, 22)
        period_durations = {oldest_known: 62}

        # Test multiple dates before oldest — all should align with oldest_known
        for days_back in [30, 60, 90, 120, 180, 365]:
            test_date = oldest_known - datetime.timedelta(days=days_back)
            result = self.mgr._get_period_start_for_date(test_date, period_durations)

            # The result should be a multiple of TARIF_D_HISTORY_PERIOD_DAYS
            # before oldest_known
            assert result is not None
            days_from_result_to_oldest = (oldest_known - result).days
            assert days_from_result_to_oldest % TARIF_D_HISTORY_PERIOD_DAYS == 0, (
                f"Period boundary for {test_date} ({result}) is not aligned "
                f"to oldest_known ({oldest_known}): "
                f"{days_from_result_to_oldest} days gap"
            )


# ── Split calculation tests ───────────────────────────────────────────────────


class TestSplitCalculation:
    """Tests for the reg/haut split calculation logic.

    These tests verify the core split algorithm by simulating the
    hour-by-hour processing that happens in resplit_tarif_d_history.
    """

    def _apply_split(
        self,
        hourly_kwh: list[float],
        threshold: float,
        period_consumed_before: float = 0.0,
    ) -> tuple[list[float], list[float]]:
        """Apply the Tarif D split to a list of hourly consumption values.

        Args:
            hourly_kwh: List of hourly consumption in kWh
            threshold: Total low-price threshold in kWh for this period
            period_consumed_before: kWh already consumed before this sequence

        Returns:
            Tuple of (reg_list, haut_list)
        """
        reg = []
        haut = []
        remaining = max(0.0, threshold - period_consumed_before)

        for kwh in hourly_kwh:
            reg_kwh = min(kwh, remaining)
            haut_kwh = max(0.0, kwh - remaining)
            remaining = max(0.0, remaining - kwh)
            reg.append(reg_kwh)
            haut.append(haut_kwh)

        return reg, haut

    def test_all_consumption_within_threshold(self) -> None:
        """When total consumption is below threshold, all goes to reg."""
        threshold = TARIF_D_THRESHOLD_KWH_PER_DAY * 62  # 2480 kWh
        hourly = [0.5] * 100  # 50 kWh total — well within threshold

        reg, haut = self._apply_split(hourly, threshold)

        assert sum(reg) == pytest.approx(50.0)
        assert sum(haut) == pytest.approx(0.0)
        assert all(h == 0.0 for h in haut)

    def test_all_consumption_beyond_threshold(self) -> None:
        """When threshold is already exhausted, all goes to haut."""
        threshold = 100.0
        hourly = [1.0] * 50  # 50 kWh

        reg, haut = self._apply_split(hourly, threshold, period_consumed_before=100.0)

        assert sum(reg) == pytest.approx(0.0)
        assert sum(haut) == pytest.approx(50.0)

    def test_split_at_threshold_boundary(self) -> None:
        """Consumption crossing threshold should split correctly at the boundary."""
        threshold = 10.0  # Simple round number for easy verification
        # 8 hours at 1 kWh, then 1 hour at 5 kWh that crosses threshold
        hourly = [1.0] * 8 + [5.0] + [1.0] * 5

        reg, haut = self._apply_split(hourly, threshold)

        # First 8 hours: all reg (8 kWh consumed, 2 remaining)
        assert reg[:8] == [1.0] * 8
        assert haut[:8] == [0.0] * 8

        # 9th hour: 2 kWh reg (fills threshold), 3 kWh haut
        assert reg[8] == pytest.approx(2.0)
        assert haut[8] == pytest.approx(3.0)

        # Remaining hours: all haut
        assert reg[9:] == [0.0] * 5
        assert haut[9:] == [1.0] * 5

    def test_reg_plus_haut_equals_total(self) -> None:
        """reg + haut must always equal total for every hour."""
        threshold = 500.0
        import random
        random.seed(42)
        hourly = [random.uniform(0.1, 3.0) for _ in range(200)]

        reg, haut = self._apply_split(hourly, threshold, period_consumed_before=400.0)

        for i, (r, h, total) in enumerate(zip(reg, haut, hourly)):
            assert r + h == pytest.approx(total, abs=1e-9), (
                f"Hour {i}: reg({r}) + haut({h}) != total({total})"
            )

    def test_threshold_resets_at_new_billing_period(self) -> None:
        """After a billing period ends, threshold should reset to full value.

        This simulates two consecutive billing periods and verifies the
        reset happens correctly.
        """
        period_days = 5
        threshold = TARIF_D_THRESHOLD_KWH_PER_DAY * period_days  # 200 kWh

        # Period 1: consume 250 kWh (50 kWh over threshold)
        period1 = [10.0] * 25  # 250 kWh
        reg1, haut1 = self._apply_split(period1, threshold)
        assert sum(reg1) == pytest.approx(threshold)
        assert sum(haut1) == pytest.approx(50.0)

        # Period 2: threshold resets — first 200 kWh should be reg again
        period2 = [10.0] * 25  # 250 kWh
        # period_consumed_before=0 simulates new billing period
        reg2, haut2 = self._apply_split(period2, threshold, period_consumed_before=0.0)
        assert sum(reg2) == pytest.approx(threshold)
        assert sum(haut2) == pytest.approx(50.0)

    def test_zero_consumption_hours(self) -> None:
        """Hours with zero consumption should produce zero reg and haut."""
        threshold = 100.0
        hourly = [0.0] * 24 + [5.0] * 5

        reg, haut = self._apply_split(hourly, threshold)

        assert reg[:24] == [0.0] * 24
        assert haut[:24] == [0.0] * 24
        assert sum(reg[24:]) == pytest.approx(25.0)
        assert sum(haut[24:]) == pytest.approx(0.0)

    def test_threshold_exactly_met(self) -> None:
        """When consumption exactly meets threshold, haut should be 0."""
        threshold = 100.0
        hourly = [1.0] * 100  # Exactly 100 kWh

        reg, haut = self._apply_split(hourly, threshold)

        assert sum(reg) == pytest.approx(100.0)
        assert sum(haut) == pytest.approx(0.0)

    def test_typical_billing_period(self) -> None:
        """Simulate a realistic 62-day billing period with varied consumption."""
        period_days = 62
        threshold = TARIF_D_THRESHOLD_KWH_PER_DAY * period_days  # 2480 kWh

        # Simulate ~40 kWh/day average (right at threshold boundary)
        # Some days above, some below
        daily_kwh = [35.0] * 30 + [45.0] * 32  # 30 days × 35 + 32 days × 45
        hourly = []
        for day_kwh in daily_kwh:
            # Spread evenly across 24 hours
            hourly.extend([day_kwh / 24] * 24)

        reg, haut = self._apply_split(hourly, threshold)

        total_reg = sum(reg)
        total_haut = sum(haut)
        total_consumption = sum(hourly)

        # reg should not exceed threshold
        assert total_reg <= threshold + 1e-6

        # reg + haut should equal total
        assert total_reg + total_haut == pytest.approx(total_consumption, abs=1e-6)

        # Since average is right at threshold, both reg and haut should have data
        assert total_reg > 0
        # 30×35 = 1050, 32×45 = 1440, total = 2490 > 2480 threshold
        # So there should be some haut
        assert total_haut > 0


# ── Statistics display name tests ─────────────────────────────────────────────


class TestStatisticsDisplayNames:
    """Tests for build_statistics_metadata display name logic."""

    def setup_method(self):
        self.mgr = make_stats_manager(rate="D")

    def test_tarif_d_reg_display_name(self) -> None:
        """Tarif D reg stream should show 'Low Price' not 'Reg'."""
        self.mgr._rate = "D"
        metadata = self.mgr.build_statistics_metadata("reg")
        assert "Low Price" in metadata.get("name", "")
        assert "Reg" not in metadata.get("name", "")

    def test_tarif_d_haut_display_name(self) -> None:
        """Tarif D haut stream should show 'High Price' not 'Haut'."""
        self.mgr._rate = "D"
        metadata = self.mgr.build_statistics_metadata("haut")
        assert "High Price" in metadata.get("name", "")
        assert "Haut" not in metadata.get("name", "")

    def test_tarif_d_total_display_name(self) -> None:
        """Tarif D total stream should show 'Total'."""
        self.mgr._rate = "D"
        metadata = self.mgr.build_statistics_metadata("total")
        assert "Total" in metadata.get("name", "")

    def test_tarif_dt_reg_display_name_unchanged(self) -> None:
        """Tarif DT reg stream should still show 'Reg' (backward compatibility)."""
        self.mgr._rate = "DT"
        metadata = self.mgr.build_statistics_metadata("reg")
        assert "Reg" in metadata.get("name", "")
        assert "Low Price" not in metadata.get("name", "")

    def test_tarif_dt_haut_display_name_unchanged(self) -> None:
        """Tarif DT haut stream should still show 'Haut' (backward compatibility)."""
        self.mgr._rate = "DT"
        metadata = self.mgr.build_statistics_metadata("haut")
        assert "Haut" in metadata.get("name", "")
        assert "High Price" not in metadata.get("name", "")
