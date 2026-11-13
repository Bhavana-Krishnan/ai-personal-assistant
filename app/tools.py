"""Every capability the AI agent can invoke.

Each entry in TOOLS maps  name → (python_fn, description_str, json_schema_dict).
`specs()` returns the OpenAI-style tool list for the model.
`call(name, args)` dispatches and always returns a JSON string.
"""

import json
from datetime import datetime

from . import db

# ── helpers ──────────────────────────────────────────────────────────────────

def _dt(value, field):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace(" ", "T")).isoformat(timespec="minutes")
    except ValueError:
        raise ValueError(f"{field} must be ISO like 2026-11-12T09:00, got {value!r}")

def _check(v, allowed, field):
    if v not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}, got {v!r}")
    return v

def _S(**kw):   return {"type": "string",  **kw}
def _I(**kw):   return {"type": "integer", **kw}
def _schema(props, req): return {"type": "object", "properties": props, "required": req}

DT_DESC = "ISO local datetime e.g. 2026-11-12T09:00"
APP_STATUS = {"saved","applied","screening","interview","offer","rejected","withdrawn"}
PRIORITY   = {"low","medium","high"}

# ── tasks ─────────────────────────────────────────────────────────────────────

def add_task(title, due=None, priority="medium", category="general", notes=""):
    _check(priority, PRIORITY, "priority")
    tid = db.run(
        "INSERT INTO tasks(title,due,priority,category,notes,created) VALUES(?,?,?,?,?,?)",
        (title, _dt(due,"due"), priority, category, notes or "", db.stamp()))
    return {"id": tid, "title": title, "due": due, "status": "open"}

def list_tasks(status="open", category=None):
    sql, args = "SELECT * FROM tasks WHERE 1=1", []
    if status != "all":
        sql += " AND status=?"; args.append(status)
    if category:
        sql += " AND category=?"; args.append(category)
    return db.rows(sql + " ORDER BY COALESCE(due,'9999'), id", args)

def update_task(id, title=None, due=None, priority=None, status=None, notes=None):
    cur = db.rows("SELECT * FROM tasks WHERE id=?", (id,))
    if not cur: raise ValueError(f"No task with id={id}")
    t = cur[0]
    if priority: _check(priority, PRIORITY, "priority")
    if status:   _check(status, {"open","done"}, "status")
    done = db.stamp() if status=="done" else (None if status=="open" else t["completed"])
    db.run("UPDATE tasks SET title=?,due=?,priority=?,status=?,notes=?,completed=? WHERE id=?",
           (title or t["title"], _dt(due,"due") or t["due"],
            priority or t["priority"], status or t["status"],
            notes if notes is not None else t["notes"], done, id))
    return db.rows("SELECT * FROM tasks WHERE id=?", (id,))[0]

def delete_task(id):
    db.run("DELETE FROM tasks WHERE id=?", (id,)); return {"deleted": id}

# ── calendar events ───────────────────────────────────────────────────────────

def add_event(title, start, end=None, description="", category="general",
              remind_minutes=15, repeat="none"):
    _check(repeat, {"none","daily","weekly","monthly"}, "repeat")
    eid = db.run(
        "INSERT INTO events(title,start,end,description,category,remind_minutes,repeat,created)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (title, _dt(start,"start"), _dt(end,"end"), description or "",
         category, int(remind_minutes), repeat, db.stamp()))
    return {"id": eid, "title": title, "start": start, "remind_minutes": remind_minutes}

def list_events(from_date=None, to_date=None):
    sql, args = "SELECT * FROM events WHERE 1=1", []
    if from_date: sql += " AND (substr(start,1,10)>=? OR repeat!='none')"; args.append(from_date[:10])
    if to_date:   sql += " AND substr(start,1,10)<=?"; args.append(to_date[:10])
    return db.rows(sql + " ORDER BY start", args)

def delete_event(id):
    db.run("DELETE FROM events WHERE id=?", (id,)); return {"deleted": id}

# ── memory / preferences ──────────────────────────────────────────────────────

def remember_preference(key, value):
    db.run("INSERT INTO prefs(key,value,updated) VALUES(?,?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
           (key.strip().lower(), value, db.stamp()))
    return {"saved": key.strip().lower(), "value": value}

def list_preferences():
    return db.rows("SELECT key,value FROM prefs ORDER BY key")

def forget_preference(key):
    db.run("DELETE FROM prefs WHERE key=?", (key.strip().lower(),))
    return {"forgotten": key}

def save_note(topic, content):
    nid = db.run("INSERT INTO notes(topic,content,created) VALUES(?,?,?)",
                 (topic, content, db.stamp()))
    return {"id": nid, "topic": topic}

def search_notes(query=""):
    like = f"%{query}%"
    return db.rows("SELECT id,topic,content,created FROM notes "
                   "WHERE topic LIKE ? OR content LIKE ? ORDER BY id DESC LIMIT 15",
                   (like, like))

# ── job applications ──────────────────────────────────────────────────────────

def add_application(company, role, status="saved", link="", notes="", follow_up=None):
    _check(status, APP_STATUS, "status")
    aid = db.run(
        "INSERT INTO applications(company,role,status,link,notes,follow_up,applied_on,updated)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (company, role, status, link or "", notes or "", follow_up or None,
         db.stamp()[:10] if status=="applied" else None, db.stamp()))
    return {"id": aid, "company": company, "role": role, "status": status}

def update_application(id, status=None, notes=None, follow_up=None):
    cur = db.rows("SELECT * FROM applications WHERE id=?", (id,))
    if not cur: raise ValueError(f"No application id={id}")
    a = cur[0]
    if status: _check(status, APP_STATUS, "status")
    applied = a["applied_on"] or (db.stamp()[:10] if status=="applied" else None)
    db.run("UPDATE applications SET status=?,notes=?,follow_up=?,applied_on=?,updated=? WHERE id=?",
           (status or a["status"], notes if notes is not None else a["notes"],
            follow_up or a["follow_up"], applied, db.stamp(), id))
    return db.rows("SELECT * FROM applications WHERE id=?", (id,))[0]

def list_applications(status=None):
    if status:
        return db.rows("SELECT * FROM applications WHERE status=? ORDER BY updated DESC", (status,))
    return db.rows("SELECT * FROM applications ORDER BY updated DESC")

def delete_application(id):
    db.run("DELETE FROM applications WHERE id=?", (id,)); return {"deleted": id}

# ── meal planner ──────────────────────────────────────────────────────────────

def save_meal_plan(day, meal, items, notes=""):
    day = _dt(day if "T" not in str(day) else day, "day")[:10]
    db.run("INSERT INTO meals(day,meal,items,notes) VALUES(?,?,?,?) "
           "ON CONFLICT(day,meal) DO UPDATE SET items=excluded.items,notes=excluded.notes",
           (day, meal.lower(), items, notes or ""))
    return {"day": day, "meal": meal.lower(), "items": items}

def get_meal_plan(day=None):
    if day:
        return db.rows("SELECT * FROM meals WHERE day=? ORDER BY id", (day[:10],))
    return db.rows("SELECT * FROM meals ORDER BY day DESC, id LIMIT 30")

# ── utility ───────────────────────────────────────────────────────────────────

def get_current_time():
    n = db.now_local()
    return {"now": n.isoformat(timespec="minutes"), "weekday": n.strftime("%A"),
            "date": n.strftime("%Y-%m-%d"), "timezone": db.TZ_NAME}

def get_summary():
    """Dashboard summary: open task count, today's events, pending follow-ups, today's meals."""
    today = db.now_local().strftime("%Y-%m-%d")
    open_tasks   = db.rows("SELECT COUNT(*) AS n FROM tasks WHERE status='open'")[0]["n"]
    today_events = db.rows("SELECT title,start FROM events WHERE substr(start,1,10)=?", (today,))
    follow_ups   = db.rows("SELECT company,role,follow_up FROM applications "
                            "WHERE follow_up<=? AND status NOT IN ('offer','rejected','withdrawn') "
                            "ORDER BY follow_up", (today,))
    meals        = db.rows("SELECT meal,items FROM meals WHERE day=? ORDER BY id", (today,))
    apps_active  = db.rows("SELECT COUNT(*) AS n FROM applications "
                            "WHERE status NOT IN ('rejected','withdrawn')")[0]["n"]
    return {"date": today, "open_tasks": open_tasks, "apps_active": apps_active,
            "todays_events": today_events, "overdue_followups": follow_ups, "todays_meals": meals}

# ── registry ──────────────────────────────────────────────────────────────────

PRIO_SCHEMA = _S(enum=["low","medium","high"])
RPT_SCHEMA  = _S(enum=["none","daily","weekly","monthly"])

TOOLS: dict[str, tuple] = {
  "get_current_time":    (get_current_time,   "Get today's local date, time and weekday. Always call this before resolving 'today', 'tomorrow' etc.", _schema({}, [])),
  "get_summary":         (get_summary,        "Get a dashboard summary: open tasks, today's events, follow-ups due, today's meals.", _schema({}, [])),
  "add_task":            (add_task,           "Create a to-do task.",
                          _schema({"title":_S(),"due":_S(description=DT_DESC),"priority":PRIO_SCHEMA,
                                   "category":_S(description="career|study|baby|business|home|general"),"notes":_S()}, ["title"])),
  "list_tasks":          (list_tasks,         "List tasks (status: open|done|all).",
                          _schema({"status":_S(enum=["open","done","all"]),"category":_S()}, [])),
  "update_task":         (update_task,        "Edit a task or mark it done.",
                          _schema({"id":_I(),"title":_S(),"due":_S(),"priority":PRIO_SCHEMA,
                                   "status":_S(enum=["open","done"]),"notes":_S()}, ["id"])),
  "delete_task":         (delete_task,        "Delete a task.", _schema({"id":_I()}, ["id"])),
  "add_event":           (add_event,          "Schedule a calendar event with an alarm reminder. Use repeat for recurring items.",
                          _schema({"title":_S(),"start":_S(description=DT_DESC),"end":_S(description=DT_DESC),
                                   "description":_S(),"category":_S(),"remind_minutes":_I(description="minutes before start to alert"),
                                   "repeat":RPT_SCHEMA}, ["title","start"])),
  "list_events":         (list_events,        "List calendar events between two dates (YYYY-MM-DD).",
                          _schema({"from_date":_S(),"to_date":_S()}, [])),
  "delete_event":        (delete_event,       "Delete a calendar event.", _schema({"id":_I()}, ["id"])),
  "remember_preference": (remember_preference,"Store a durable preference or personal fact (wake_time, baby_age, study_hours…).",
                          _schema({"key":_S(description="short snake_case key"),"value":_S()}, ["key","value"])),
  "list_preferences":    (list_preferences,   "List all remembered preferences.", _schema({}, [])),
  "forget_preference":   (forget_preference,  "Delete a remembered preference.", _schema({"key":_S()}, ["key"])),
  "save_note":           (save_note,          "Save a longer note under a topic (e.g. 'business-sister', 'study-ml').",
                          _schema({"topic":_S(),"content":_S()}, ["topic","content"])),
  "search_notes":        (search_notes,       "Search saved notes by keyword.", _schema({"query":_S()}, [])),
  "add_application":     (add_application,    "Track a new job application.",
                          _schema({"company":_S(),"role":_S(),"status":_S(enum=sorted(APP_STATUS)),
                                   "link":_S(),"notes":_S(),"follow_up":_S(description="YYYY-MM-DD")}, ["company","role"])),
  "update_application":  (update_application, "Update application status/notes/follow-up.",
                          _schema({"id":_I(),"status":_S(enum=sorted(APP_STATUS)),"notes":_S(),"follow_up":_S()}, ["id"])),
  "list_applications":   (list_applications,  "List tracked job applications, optionally filtered by status.",
                          _schema({"status":_S(description="|".join(sorted(APP_STATUS)))}, [])),
  "delete_application":  (delete_application, "Delete a tracked application.", _schema({"id":_I()}, ["id"])),
  "save_meal_plan":      (save_meal_plan,     "Save one meal slot for a day.",
                          _schema({"day":_S(description="YYYY-MM-DD"),"meal":_S(description="breakfast|lunch|snack|dinner"),
                                   "items":_S(description="comma-separated food items"),"notes":_S()}, ["day","meal","items"])),
  "get_meal_plan":       (get_meal_plan,      "Get the meal plan for a day or the latest 30 entries.",
                          _schema({"day":_S(description="YYYY-MM-DD – omit for latest")}, [])),
}


def specs() -> list[dict]:
    return [{"name": n, "description": d, "parameters": p} for n,(_, d, p) in TOOLS.items()]


def call(name: str, args) -> str:
    try:
        if name not in TOOLS:
            raise ValueError(f"Unknown tool: {name}")
        if isinstance(args, str):
            args = json.loads(args or "{}")
        result = TOOLS[name][0](**(args or {}))
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    return json.dumps(result, ensure_ascii=False, default=str)
