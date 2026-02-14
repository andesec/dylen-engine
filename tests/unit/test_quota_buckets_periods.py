from __future__ import annotations

import datetime

from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import period_start_date


def test_period_start_date_week_starts_monday_utc() -> None:
  now = datetime.datetime(2026, 2, 3, 12, 0, 0, tzinfo=datetime.UTC)  # Tuesday
  start = period_start_date(now=now, period=QuotaPeriod.WEEK)
  assert start == datetime.date(2026, 2, 2)  # Monday


def test_period_start_date_month_starts_first_utc() -> None:
  now = datetime.datetime(2026, 2, 3, 12, 0, 0, tzinfo=datetime.UTC)
  start = period_start_date(now=now, period=QuotaPeriod.MONTH)
  assert start == datetime.date(2026, 2, 1)
