"""Construction du trigger APScheduler à partir du paramètre ``schedule``."""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


def build_trigger(schedule: int | str) -> IntervalTrigger | CronTrigger:
    """``schedule`` = intervalle en secondes (int / chiffres) ou expression cron (str)."""
    if isinstance(schedule, int):
        return IntervalTrigger(seconds=schedule)
    text = str(schedule).strip()
    if text.isdigit():
        return IntervalTrigger(seconds=int(text))
    return CronTrigger.from_crontab(text)
