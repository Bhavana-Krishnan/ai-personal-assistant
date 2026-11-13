"""Unit tests for the tools layer. Uses a temp SQLite database, no real API calls."""
import os, sys, json, tempfile, pytest
from pathlib import Path
from datetime import datetime

# point to a temp data dir before importing anything
_tmpdir = tempfile.mkdtemp()
os.environ["PA_DATA_DIR"] = _tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, tools as T
from app.calendar_ics import build_ics


# ── time ────────────────────────────────────────────────────────────────────

def test_get_current_time():
    t = T.get_current_time()
    assert "now" in t and "weekday" in t and "timezone" in t


# ── tasks ────────────────────────────────────────────────────────────────────

def test_add_list_update_delete_task():
    t = T.add_task("Buy milk", due="2026-12-01", priority="low", category="home")
    assert t["id"] > 0

    tasks = T.list_tasks(status="open")
    titles = [x["title"] for x in tasks]
    assert "Buy milk" in titles

    updated = T.update_task(id=t["id"], priority="high")
    assert updated["priority"] == "high"

    done = T.update_task(id=t["id"], status="done")
    assert done["status"] == "done"
    assert done["completed"] is not None

    T.delete_task(id=t["id"])
    remaining = [x for x in T.list_tasks("all") if x["id"] == t["id"]]
    assert remaining == []


def test_task_bad_priority():
    result = json.loads(T.call("add_task", {"title": "X", "priority": "critical"}))
    assert "error" in result


def test_task_category_filter():
    T.add_task("Career task", category="career")
    T.add_task("Baby task",   category="baby")
    career = T.list_tasks(category="career")
    assert all(x["category"] == "career" for x in career)


# ── events ───────────────────────────────────────────────────────────────────

def test_add_list_delete_event():
    ev = T.add_event("Morning yoga", start="2026-12-05T07:00", remind_minutes=10, repeat="daily")
    assert ev["id"] > 0

    evs = T.list_events()
    assert any(e["title"] == "Morning yoga" for e in evs)

    T.delete_event(id=ev["id"])
    after = T.list_events()
    assert not any(e["id"] == ev["id"] for e in after)


# ── preferences ──────────────────────────────────────────────────────────────

def test_prefs_roundtrip():
    T.remember_preference("wake_time", "6:30 AM")
    T.remember_preference("study_hours", "2")
    p = {x["key"]: x["value"] for x in T.list_preferences()}
    assert p["wake_time"] == "6:30 AM"
    assert p["study_hours"] == "2"

    T.remember_preference("wake_time", "7:00 AM")   # update
    p2 = {x["key"]: x["value"] for x in T.list_preferences()}
    assert p2["wake_time"] == "7:00 AM"

    T.forget_preference("study_hours")
    p3 = {x["key"] for x in T.list_preferences()}
    assert "study_hours" not in p3


# ── notes ────────────────────────────────────────────────────────────────────

def test_save_search_notes():
    T.save_note("business-sister", "Decided to stock Rose-gold bangles for Dec.")
    results = T.search_notes("bangles")
    assert any("bangles" in n["content"] for n in results)

    all_notes = T.search_notes("")
    assert len(all_notes) > 0


# ── applications ─────────────────────────────────────────────────────────────

def test_applications():
    a = T.add_application("Biotech Corp", "Data Analyst", status="saved")
    assert a["id"] > 0

    T.update_application(id=a["id"], status="applied")
    apps = T.list_applications(status="applied")
    assert any(x["company"] == "Biotech Corp" for x in apps)

    T.delete_application(id=a["id"])
    after = T.list_applications()
    assert not any(x["id"] == a["id"] for x in after)


# ── meals ────────────────────────────────────────────────────────────────────

def test_meals():
    T.save_meal_plan("2026-12-01", "breakfast", "Oatmeal, banana")
    T.save_meal_plan("2026-12-01", "lunch",     "Khichdi, curd")
    meals = T.get_meal_plan("2026-12-01")
    assert len(meals) == 2
    assert meals[0]["items"] == "Oatmeal, banana"

    # update (upsert)
    T.save_meal_plan("2026-12-01", "breakfast", "Rice porridge")
    meals2 = T.get_meal_plan("2026-12-01")
    assert any(m["items"] == "Rice porridge" for m in meals2)


# ── summary ──────────────────────────────────────────────────────────────────

def test_get_summary():
    s = T.get_summary()
    assert "open_tasks" in s and "apps_active" in s


# ── calendar ics ─────────────────────────────────────────────────────────────

def test_build_ics():
    T.add_event("Test alarm", start="2026-12-10T09:00", remind_minutes=20)
    T.add_task("Deadline task", due="2026-12-10")
    ics = build_ics()
    assert "BEGIN:VCALENDAR" in ics
    assert "VEVENT" in ics
    assert "VALARM" in ics


# ── tool dispatcher ──────────────────────────────────────────────────────────

def test_call_dispatcher():
    r = json.loads(T.call("get_current_time", {}))
    assert "now" in r

    r2 = json.loads(T.call("unknown_tool", {}))
    assert "error" in r2

    r3 = json.loads(T.call("add_task", '{"title":"Dispatcher test"}'))
    assert "id" in r3
