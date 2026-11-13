"""FastAPI backend for the AI Personal Assistant."""

import json
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from . import db, tools as T
from .llm import run_agent, list_openai_models, list_anthropic_models, complete, SYSTEM_PROMPT
from .calendar_ics import build_ics
from .workflows import (workflow_daily_plan, workflow_baby_meals, workflow_career_plan,
                        workflow_study_plan, workflow_business_notes, workflow_weekly_review,
                        WORKFLOWS)

# ── in-memory session state ───────────────────────────────────────────────────
# (single-user; for multi-user extend with session tokens)
_session: dict = {"history": [], "provider": "anthropic", "api_key": "", "model": "claude-3-5-sonnet-20241022"}

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TEMPLATE   = (Path(__file__).resolve().parent.parent / "templates" / "index.html").read_text()


# ── helpers ───────────────────────────────────────────────────────────────────

def _json(data, status=200):
    return JSONResponse(data, status_code=status)

def _err(msg, status=400):
    return _json({"error": msg}, status)

async def _body(req: Request) -> dict:
    try:
        return await req.json()
    except Exception:
        return {}


# ── settings ──────────────────────────────────────────────────────────────────

async def get_settings(req):
    return _json({"provider": _session["provider"], "model": _session["model"],
                  "has_key": bool(_session["api_key"])})

async def save_settings(req):
    b = await _body(req)
    if "provider" in b:
        if b["provider"] not in ("openai","anthropic"):
            return _err("provider must be openai or anthropic")
        _session["provider"] = b["provider"]
    if "api_key" in b:
        _session["api_key"] = b["api_key"].strip()
    if "model" in b:
        _session["model"] = b["model"].strip()
    # persist to env-file so restart remembers (optional, best-effort)
    envf = db.DATA_DIR / ".env"
    try:
        envf.write_text(f'PA_PROVIDER={_session["provider"]}\nPA_MODEL={_session["model"]}\n')
    except Exception:
        pass
    return _json({"ok": True})

async def list_models(req):
    provider = req.query_params.get("provider", _session["provider"])
    key = req.query_params.get("api_key", _session["api_key"])
    if not key:
        defaults = {"openai": ["gpt-4o","gpt-4o-mini","gpt-3.5-turbo"],
                    "anthropic": ["claude-3-5-sonnet-20241022","claude-3-haiku-20240307","claude-sonnet-4-5"]}
        return _json(defaults.get(provider, []))
    if provider == "openai":
        return _json(list_openai_models(key))
    return _json(list_anthropic_models(key))


# ── chat ──────────────────────────────────────────────────────────────────────

async def chat(req):
    b = await _body(req)
    msg = (b.get("message") or "").strip()
    if not msg:
        return _err("message required")
    key = _session["api_key"]
    if not key:
        return _err("API key not set. Go to ⚙️ Settings first.")

    # Save user message
    db.run("INSERT INTO chat(role,content,created) VALUES(?,?,?)", ("user", msg, db.stamp()))

    try:
        reply, new_history = run_agent(
            msg, _session["history"],
            _session["provider"], key, _session["model"])
    except Exception as e:
        return _err(f"LLM error: {e}", 500)

    _session["history"] = new_history[-30:]   # keep last 30 turns
    db.run("INSERT INTO chat(role,content,created) VALUES(?,?,?)", ("assistant", reply, db.stamp()))
    return _json({"reply": reply})

async def clear_chat(req):
    _session["history"] = []
    return _json({"ok": True})

async def get_history(req):
    rows = db.rows("SELECT role,content,created FROM chat ORDER BY id DESC LIMIT 40")
    return _json(list(reversed(rows)))


# ── dashboard ─────────────────────────────────────────────────────────────────

async def dashboard(req):
    return _json(T.get_summary())


# ── tasks ─────────────────────────────────────────────────────────────────────

async def tasks_list(req):
    status   = req.query_params.get("status","open")
    category = req.query_params.get("category")
    return _json(T.list_tasks(status=status, category=category))

async def tasks_create(req):
    b = await _body(req)
    if not b.get("title"): return _err("title required")
    return _json(T.add_task(**{k:v for k,v in b.items() if k in ("title","due","priority","category","notes")}))

async def tasks_update(req):
    tid = int(req.path_params["id"])
    b = await _body(req)
    return _json(T.update_task(id=tid, **{k:v for k,v in b.items() if k in ("title","due","priority","status","notes")}))

async def tasks_delete(req):
    tid = int(req.path_params["id"])
    return _json(T.delete_task(id=tid))


# ── events ────────────────────────────────────────────────────────────────────

async def events_list(req):
    return _json(T.list_events(req.query_params.get("from_date"), req.query_params.get("to_date")))

async def events_create(req):
    b = await _body(req)
    if not b.get("title"): return _err("title required")
    if not b.get("start"): return _err("start required")
    return _json(T.add_event(**{k:v for k,v in b.items() if k in ("title","start","end","description","category","remind_minutes","repeat")}))

async def events_delete(req):
    return _json(T.delete_event(id=int(req.path_params["id"])))


# ── applications ──────────────────────────────────────────────────────────────

async def apps_list(req):
    return _json(T.list_applications(req.query_params.get("status")))

async def apps_create(req):
    b = await _body(req)
    if not b.get("company"): return _err("company required")
    if not b.get("role"):    return _err("role required")
    return _json(T.add_application(**{k:v for k,v in b.items() if k in ("company","role","status","link","notes","follow_up")}))

async def apps_update(req):
    b = await _body(req)
    return _json(T.update_application(id=int(req.path_params["id"]),
                 **{k:v for k,v in b.items() if k in ("status","notes","follow_up")}))

async def apps_delete(req):
    return _json(T.delete_application(id=int(req.path_params["id"])))


# ── meals ─────────────────────────────────────────────────────────────────────

async def meals_get(req):
    return _json(T.get_meal_plan(req.query_params.get("day")))

async def meals_save(req):
    b = await _body(req)
    return _json(T.save_meal_plan(**{k:v for k,v in b.items() if k in ("day","meal","items","notes")}))


# ── preferences ───────────────────────────────────────────────────────────────

async def prefs_list(req):  return _json(T.list_preferences())

async def prefs_save(req):
    b = await _body(req)
    return _json(T.remember_preference(b["key"], b["value"]))

async def prefs_delete(req):
    return _json(T.forget_preference(req.path_params["key"]))


# ── notes ─────────────────────────────────────────────────────────────────────

async def notes_search(req):
    return _json(T.search_notes(req.query_params.get("q","")))

async def notes_save(req):
    b = await _body(req)
    return _json(T.save_note(b["topic"], b["content"]))


# ── workflows ─────────────────────────────────────────────────────────────────

async def run_workflow(req):
    name = req.path_params["name"]
    b    = await _body(req)
    key  = _session["api_key"]
    if not key:
        return _err("API key not set. Go to Settings first.")
    prov  = _session["provider"]
    model = _session["model"]

    try:
        if name == "daily_plan":
            result = workflow_daily_plan(prov, key, model)
        elif name == "baby_meals":
            result = workflow_baby_meals(prov, key, model)
        elif name == "career_plan":
            result = workflow_career_plan(prov, key, model)
        elif name == "study_plan":
            result = workflow_study_plan(prov, key, model)
        elif name == "business_notes":
            discussion = b.get("discussion","")
            if not discussion:
                return _err("discussion text required for business_notes")
            result = workflow_business_notes(discussion, prov, key, model)
        elif name == "weekly_review":
            result = workflow_weekly_review(prov, key, model)
        else:
            return _err(f"Unknown workflow: {name}")
    except Exception as e:
        return _err(f"Workflow error: {e}", 500)

    return _json({"result": result})

async def list_workflows(req):
    return _json([{"id": k, "name": v[0], "description": v[1]} for k,v in WORKFLOWS.items()])


# ── calendar .ics ─────────────────────────────────────────────────────────────

async def ics_feed(req):
    return Response(build_ics(), media_type="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=personal-assistant.ics"})


# ── UI ────────────────────────────────────────────────────────────────────────

async def index(req):
    return HTMLResponse(TEMPLATE)


# ── routing ───────────────────────────────────────────────────────────────────

routes = [
    Route("/",                    index),
    Route("/api/settings",        get_settings,  methods=["GET"]),
    Route("/api/settings",        save_settings, methods=["POST"]),
    Route("/api/models",          list_models,   methods=["GET"]),
    Route("/api/chat",            chat,          methods=["POST"]),
    Route("/api/chat/history",    get_history,   methods=["GET"]),
    Route("/api/chat/clear",      clear_chat,    methods=["POST"]),
    Route("/api/dashboard",       dashboard,     methods=["GET"]),
    Route("/api/tasks",           tasks_list,    methods=["GET"]),
    Route("/api/tasks",           tasks_create,  methods=["POST"]),
    Route("/api/tasks/{id:int}",  tasks_update,  methods=["PATCH"]),
    Route("/api/tasks/{id:int}",  tasks_delete,  methods=["DELETE"]),
    Route("/api/events",          events_list,   methods=["GET"]),
    Route("/api/events",          events_create, methods=["POST"]),
    Route("/api/events/{id:int}", events_delete, methods=["DELETE"]),
    Route("/api/applications",    apps_list,     methods=["GET"]),
    Route("/api/applications",    apps_create,   methods=["POST"]),
    Route("/api/applications/{id:int}", apps_update, methods=["PATCH"]),
    Route("/api/applications/{id:int}", apps_delete, methods=["DELETE"]),
    Route("/api/meals",           meals_get,     methods=["GET"]),
    Route("/api/meals",           meals_save,    methods=["POST"]),
    Route("/api/prefs",           prefs_list,    methods=["GET"]),
    Route("/api/prefs",           prefs_save,    methods=["POST"]),
    Route("/api/prefs/{key}",     prefs_delete,  methods=["DELETE"]),
    Route("/api/notes",           notes_search,  methods=["GET"]),
    Route("/api/notes",           notes_save,    methods=["POST"]),
    Route("/api/workflows",       list_workflows,methods=["GET"]),
    Route("/api/workflows/{name}",run_workflow,  methods=["POST"]),
    Route("/calendar.ics",        ics_feed,      methods=["GET"]),
    Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
]


def create_app():
    # Load persisted settings on startup
    envf = db.DATA_DIR / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k == "PA_PROVIDER": _session["provider"] = v
                if k == "PA_MODEL":    _session["model"]    = v
    # Honour env-var API keys if set
    if os.environ.get("OPENAI_API_KEY"):
        _session["api_key"]  = os.environ["OPENAI_API_KEY"]
        _session["provider"] = "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        _session["api_key"]  = os.environ["ANTHROPIC_API_KEY"]
        _session["provider"] = "anthropic"
    return Starlette(routes=routes)
