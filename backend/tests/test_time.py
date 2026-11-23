from datetime import datetime, timedelta, timezone

from matchedge.engine.analysis import prematch_status
from matchedge.timeutil import (dataset_kickoff_utc, local_date_bounds, local_input_to_utc, local_str,
                                time_certainty)


def test_winter_conversion_to_belgrade():
    utc = dataset_kickoff_utc("2026-11-24", "21:00")
    assert utc == datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)
    assert local_str(utc) == "2026-11-24 21:00"


def test_summer_conversion_and_uncertainty_flag():
    utc = dataset_kickoff_utc("2026-08-22", "17:30")
    assert utc == datetime(2026, 8, 22, 16, 30, tzinfo=timezone.utc)
    assert local_str(utc) == "2026-08-22 18:30"  # CEST = UTC+2
    label, notes = time_certainty("2026-08-22", "17:30", None, utc)
    assert label == "uncertain"


def test_blank_time_is_unknown_not_midnight():
    assert dataset_kickoff_utc("2026-11-24", "") is None
    assert dataset_kickoff_utc("2026-11-24", None) is None
    assert time_certainty("2026-11-24", "", None, None)[0] == "unknown"


def test_snapshot_agreement_and_conflict():
    ds = dataset_kickoff_utc("2026-11-30", "20:45")
    assert time_certainty("2026-11-30", "20:45", ds, ds)[0] == "corroborated"
    assert time_certainty("2026-11-30", "20:45", ds + timedelta(hours=1), ds)[0] == "conflict"


def test_local_input_and_day_bounds():
    assert local_input_to_utc("2026-07-01 20:00") == datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)
    s, e = local_date_bounds("2026-11-24")
    assert s == datetime(2026, 11, 23, 23, 0, tzinfo=timezone.utc) and e - s == timedelta(days=1)


def test_started_completed_postponed_are_excluded():
    now = datetime(2026, 11, 24, 20, 30, tzinfo=timezone.utc)
    ko_past = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)
    ko_future = datetime(2026, 11, 24, 21, 0, tzinfo=timezone.utc)
    assert prematch_status("scheduled", ko_past, "2026-11-24", now, "Europe/Belgrade", False)[0] is False
    assert prematch_status("scheduled", ko_future, "2026-11-24", now, "Europe/Belgrade", False) == (True, "scheduled")
    assert prematch_status("finished", ko_future, "2026-11-24", now, "Europe/Belgrade", False)[0] is False
    assert prematch_status("postponed", ko_future, "2026-11-24", now, "Europe/Belgrade", False)[0] is False
    assert prematch_status("cancelled", ko_future, "2026-11-24", now, "Europe/Belgrade", False)[0] is False
    assert prematch_status("missing_from_source", ko_future, "2026-11-24", now, "Europe/Belgrade", False)[0] is False
    # unknown kickoff on the same local day cannot be confirmed as not started
    assert prematch_status("scheduled", None, "2026-11-24", now, "Europe/Belgrade", False)[0] is False
    assert prematch_status("scheduled", None, "2026-11-26", now, "Europe/Belgrade", False)[0] is True
