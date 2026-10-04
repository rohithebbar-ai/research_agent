from datetime import datetime, timedelta, timezone

from tools.runs import is_stale, run_state

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def at(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def test_a_recently_touched_run_is_not_stale():
    assert not is_stale({"updated_at": at(1)}, 360, NOW)


def test_a_run_untouched_for_longer_than_a_run_can_take_is_stale():
    assert is_stale({"updated_at": at(10)}, 360, NOW)


def test_a_record_with_no_timestamps_counts_as_stale():
    assert is_stale({}, 360, NOW)


def test_run_state_covers_running_crashed_error_and_old_records():
    assert run_state({"status": "running", "updated_at": at(1)}, 360, NOW) == "running"
    assert run_state({"status": "running", "updated_at": at(30)}, 360, NOW) == "crashed"
    assert run_state({"status": "error"}, 360, NOW) == "error"
    assert run_state({"status": "done"}, 360, NOW) == "done"
    assert run_state({"stopped_reason": "finished"}, 360, NOW) == "done"   # saved before the status field existed
