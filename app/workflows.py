"""Pre-built multi-step AI workflows. Each workflow gathers context from the DB,
calls the LLM for structured output, then saves results back via tools.

Workflows are real agents: they chain multiple LLM calls + tool calls
rather than being simple single-turn completions.
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, tools as T
from .llm import complete, SYSTEM_PROMPT


def _today() -> str:
    return db.now_local().strftime("%Y-%m-%d")


def _prefs_text() -> str:
    prefs = T.list_preferences()
    if not prefs:
        return "No preferences saved yet."
    return "\n".join(f"  {p['key']}: {p['value']}" for p in prefs)


def _extract_json(text: str) -> list | dict:
    """Pull the first JSON array or object out of an LLM response."""
    decoder = json.JSONDecoder()
    starts = sorted(
        pos for pos in (text.find("{"), text.find("[")) if pos != -1
    )

    for start in starts:
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue

        if isinstance(value, (list, dict)):
            return value

    return []


# ── 1. Daily Plan ─────────────────────────────────────────────────────────────

def workflow_daily_plan(provider, api_key, model) -> str:
    today   = _today()
    tasks   = T.list_tasks(status="open")
    apps    = T.list_applications()
    meals   = T.get_meal_plan(today)
    prefs   = _prefs_text()

    context = f"""
Today: {today}
User preferences:\n{prefs}
Open tasks ({len(tasks)}): {json.dumps(tasks[:8], default=str)}
Active applications ({len(apps)}): {json.dumps([a for a in apps if a['status'] not in ('rejected','withdrawn')][:5], default=str)}
Today's meals: {json.dumps(meals, default=str)}
"""
    prompt = (
        "Create an optimised daily plan for today. "
        "Return a JSON array where each item is:\n"
        '{"time":"HH:MM","activity":"...","category":"career|study|baby|business|home|general","duration_min":30}\n'
        "Cover work blocks, study slots, baby care, business time, meals, and breaks. "
        "Use the saved preferences to pick realistic times.\n\nContext:\n" + context
    )
    raw = complete(prompt, SYSTEM_PROMPT, provider, api_key, model)

    try:
        slots = _extract_json(raw)
        if not isinstance(slots, list):
            raise ValueError("not a list")
    except Exception:
        return f"Here is your daily plan:\n\n{raw}"

    # save each time slot as an event
    saved = 0
    for slot in slots[:12]:
        try:
            start_dt = f"{today}T{slot.get('time','09:00')}"
            dur = int(slot.get("duration_min", 30))
            start = datetime.fromisoformat(start_dt)
            end   = (start + timedelta(minutes=dur)).isoformat(timespec="minutes")
            T.add_event(title=slot["activity"], start=start_dt, end=end,
                        category=slot.get("category","general"), remind_minutes=5)
            saved += 1
        except Exception:
            pass

    lines = [f"✅ Created {saved} calendar events for today.\n", "**Today's Plan**\n"]
    for s in slots:
        lines.append(f"🕐 {s.get('time','')}  {s.get('activity','')}  ({s.get('duration_min','')} min)")
    lines.append("\n📅 Import the .ics feed to get these reminders on your phone.")
    return "\n".join(lines)


# ── 2. Baby Meal Planner ──────────────────────────────────────────────────────

def workflow_baby_meals(provider, api_key, model) -> str:
    today  = _today()
    prefs  = _prefs_text()
    prompt = (
        f"Today is {today}. Plan nutritious meals for a baby/toddler for today.\n"
        "Return a JSON array:\n"
        '[{"meal":"breakfast","items":"...","notes":""},...]\n'
        "Include breakfast, morning snack, lunch, afternoon snack, dinner.\n"
        "Vary textures and nutrients. Keep items age-appropriate.\n"
        f"Saved preferences:\n{prefs}"
    )
    raw = complete(prompt, SYSTEM_PROMPT, provider, api_key, model)
    try:
        plan = _extract_json(raw)
        if not isinstance(plan, list): raise ValueError
    except Exception:
        return f"Baby meal plan:\n\n{raw}"

    saved = 0
    for m in plan:
        try:
            T.save_meal_plan(day=today, meal=m["meal"], items=m["items"],
                             notes=m.get("notes",""))
            saved += 1
        except Exception:
            pass

    lines = [f"🍼 Saved {saved} meal slots for today.\n", "**Baby Meal Plan**\n"]
    for m in plan:
        lines.append(f"• **{m.get('meal','').title()}**: {m.get('items','')}  — {m.get('notes','')}")
    return "\n".join(lines)


# ── 3. Career Plan ────────────────────────────────────────────────────────────

def workflow_career_plan(provider, api_key, model) -> str:
    apps   = T.list_applications()
    tasks  = T.list_tasks(category="career")
    prefs  = _prefs_text()

    context = (
        f"Applications: {json.dumps(apps, default=str)}\n"
        f"Career tasks: {json.dumps(tasks, default=str)}\n"
        f"Preferences:\n{prefs}"
    )
    # Step 1 — analyse
    analysis = complete(
        f"Analyse this job-search situation and identify the top 3 priority actions:\n{context}",
        SYSTEM_PROMPT, provider, api_key, model)

    # Step 2 — create tasks
    plan_prompt = (
        "Based on this analysis, return a JSON array of career tasks:\n"
        '[{"title":"...","due":"YYYY-MM-DD","priority":"high|medium|low","notes":""},...]\n'
        "Include: application follow-ups, skill prep, interview prep, networking.\n"
        f"Analysis:\n{analysis}"
    )
    raw = complete(plan_prompt, SYSTEM_PROMPT, provider, api_key, model)
    try:
        new_tasks = _extract_json(raw)
        if not isinstance(new_tasks, list): raise ValueError
    except Exception:
        return f"Career analysis:\n\n{analysis}\n\nTask suggestions:\n\n{raw}"

    saved = 0
    for t in new_tasks[:8]:
        try:
            T.add_task(title=t["title"], due=t.get("due"), priority=t.get("priority","medium"),
                       category="career", notes=t.get("notes",""))
            saved += 1
        except Exception:
            pass

    lines = ["**Career Analysis**\n", analysis, f"\n\n✅ Created {saved} career tasks.\n",
             "**New Tasks**"]
    for t in new_tasks:
        lines.append(f"• [{t.get('priority','').upper()}] {t.get('title','')} — due {t.get('due','')}")
    return "\n".join(lines)


# ── 4. Study Plan ─────────────────────────────────────────────────────────────

def workflow_study_plan(provider, api_key, model) -> str:
    tasks  = T.list_tasks(category="study")
    prefs  = _prefs_text()
    today  = _today()
    prompt = (
        f"Today: {today}\nStudy tasks: {json.dumps(tasks, default=str)}\nPrefs:\n{prefs}\n"
        "Create a 7-day study schedule. Return JSON array:\n"
        '[{"day":"YYYY-MM-DD","topic":"...","duration_min":60,"goal":"..."},...]\n'
        "Cover AI/ML, bioinformatics, Python, and any topics in prefs or tasks."
    )
    raw = complete(prompt, SYSTEM_PROMPT, provider, api_key, model)
    try:
        schedule = _extract_json(raw)
        if not isinstance(schedule, list): raise ValueError
    except Exception:
        return f"Study plan:\n\n{raw}"

    saved = 0
    for s in schedule[:7]:
        try:
            T.add_task(title=f"Study: {s['topic']}", due=s.get("day"),
                       priority="medium", category="study",
                       notes=f"Goal: {s.get('goal','')} | {s.get('duration_min',60)} min")
            saved += 1
        except Exception:
            pass

    lines = [f"📚 Created {saved} study tasks.\n", "**7-Day Study Schedule**\n"]
    for s in schedule:
        lines.append(f"• {s.get('day','')} — **{s.get('topic','')}** "
                     f"({s.get('duration_min','')} min) | {s.get('goal','')}")
    return "\n".join(lines)


# ── 5. Business Meeting Notes ─────────────────────────────────────────────────

def workflow_business_notes(discussion: str, provider, api_key, model) -> str:
    prompt = (
        "You're summarising a business discussion between Bhavana and her sister for a jewellery brand.\n"
        "Extract: decisions made, action items, unresolved questions.\n"
        "Return JSON: {\"decisions\":[...],\"actions\":[{\"task\":\"...\",\"owner\":\"Bhavana|Sister\",\"due\":\"YYYY-MM-DD\"}],\"open\":[...]}\n"
        f"Discussion:\n{discussion}"
    )
    raw = complete(prompt, SYSTEM_PROMPT, provider, api_key, model)
    try:
        data = _extract_json(raw)
        if not isinstance(data, dict): raise ValueError
    except Exception:
        T.save_note("business-sister", discussion)
        return f"Notes saved.\n\n{raw}"

    T.save_note("business-sister",
                f"Discussion:\n{discussion}\n\nSummary:\n{json.dumps(data, indent=2)}")
    saved = 0
    for a in data.get("actions", []):
        if a.get("owner","").lower().startswith("bhavana"):
            try:
                T.add_task(title=a["task"], due=a.get("due"),
                           priority="high", category="business",
                           notes="Action from sister meeting")
                saved += 1
            except Exception:
                pass

    lines = ["📝 Notes saved + " + (f"{saved} tasks created." if saved else "No personal tasks this time."),
             "\n**Decisions**"]
    for d in data.get("decisions", []):
        lines.append(f"• {d}")
    lines.append("\n**Your Action Items**")
    for a in data.get("actions", []):
        marker = "👤" if a.get("owner","").lower().startswith("bhavana") else "👭"
        lines.append(f"{marker} {a.get('task','')} — due {a.get('due','')} ({a.get('owner','')})")
    if data.get("open"):
        lines.append("\n**Open Questions**")
        for q in data["open"]:
            lines.append(f"• {q}")
    return "\n".join(lines)


# ── 6. Weekly Review ──────────────────────────────────────────────────────────

def workflow_weekly_review(provider, api_key, model) -> str:
    done  = T.list_tasks(status="done")
    open_ = T.list_tasks(status="open")
    apps  = T.list_applications()
    notes = T.search_notes("")
    context = (
        f"Completed tasks: {json.dumps(done[-20:], default=str)}\n"
        f"Open tasks: {json.dumps(open_[:15], default=str)}\n"
        f"Applications: {json.dumps(apps[:10], default=str)}\n"
        f"Notes: {json.dumps([n['topic'] for n in notes], default=str)}"
    )
    raw = complete(
        f"Write a friendly weekly review. Celebrate wins, flag blockers, suggest 3 priorities for next week.\n\n{context}",
        SYSTEM_PROMPT, provider, api_key, model)
    T.save_note("weekly-review", raw)
    return f"**Weekly Review**\n\n{raw}\n\n_(Saved to notes)_"


# ── dispatch ──────────────────────────────────────────────────────────────────

WORKFLOWS = {
    "daily_plan":      ("🗓️ Daily Plan",         "Create today's time-blocked schedule",   workflow_daily_plan),
    "baby_meals":      ("🍼 Baby Meal Planner",   "Plan baby's meals for today",            workflow_baby_meals),
    "career_plan":     ("💼 Career Plan",         "Analyse applications & create tasks",    workflow_career_plan),
    "study_plan":      ("📚 Study Plan",          "Build a 7-day study schedule",           workflow_study_plan),
    "business_notes":  ("👭 Business Notes",      "Summarise a sister discussion",          None),   # needs discussion text
    "weekly_review":   ("📊 Weekly Review",       "Review the week & plan ahead",           workflow_weekly_review),
}
