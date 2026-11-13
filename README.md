# AI Personal Assistant

A fully-working AI Personal Assistant built with **Python + FastAPI + Starlette**, powered by **Claude (Anthropic) or GPT (OpenAI)** via real tool-calling agents — not just a simple chatbot.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **Tool-Calling Agent** | Multi-step agent loop using OpenAI function-calling or Anthropic tool-use — calls 20 tools per turn |
| 🧠 **Persistent Memory** | Saves preferences, notes and habits to SQLite; recalled automatically every conversation |
| ⚡ **6 AI Workflows** | Daily Plan, Baby Meals, Career Plan, Study Plan, Business Notes, Weekly Review |
| ✅ **Task Manager** | Priority, categories (career / study / baby / business / home), due dates |
| 📅 **Calendar + Reminders** | .ics feed — subscribe in Google Calendar / Apple Calendar / Outlook for push-notifications |
| 💼 **Job Tracker** | Track applications through saved → applied → screening → interview → offer |
| 🍼 **Baby Meal Planner** | Plan and log daily baby meals; AI suggests nutritious options |
| 📝 **Notes** | Topic-based searchable notes (business calls, meeting decisions, etc.) |
| 🔑 **BYO API Key** | Works with Anthropic **or** OpenAI — you choose the key and model |

---

## 🏗️ Architecture

```
personal-assistant/
├── app/
│   ├── db.py            ← SQLite schema + helpers (tasks, events, prefs, meals, apps, chat)
│   ├── tools.py         ← 20 tools the agent can call (add_task, add_event, remember_preference…)
│   ├── llm.py           ← HTTP wrappers for OpenAI & Anthropic; full tool-calling agent loop
│   ├── workflows.py     ← 6 multi-step AI workflows (chain multiple LLM + tool calls)
│   ├── calendar_ics.py  ← RFC 5545 .ics builder with VALARM reminders
│   └── main.py          ← Starlette/FastAPI routes (REST API + single-page UI)
├── templates/
│   └── index.html       ← Dark-mode SPA — Dashboard, Chat, Tasks, Calendar, Workflows…
├── tests/
│   └── test_tools.py    ← 12 unit tests (no API key needed)
├── run.py               ← Entry point
├── requirements.txt
└── .env.example
```

### Agent loop (how tool-calling works)

```
User message
     │
     ▼
  LLM API  ──► tool_calls?  ──YES──► tools.call(name, args)  ──► result back to LLM
     │                                                                      │
     │◄─────────────────────────────────────────────────────────────────────┘
     │
     ▼  (up to 10 hops)
  Final text reply  ──► saved to chat history  ──► returned to UI
```

### Workflows (multi-step chains)

Each workflow does **2–3 LLM calls** plus multiple tool calls:

| Workflow | Steps |
|---|---|
| **Daily Plan** | read prefs + tasks → LLM plans time-slots → saves each slot as a calendar event |
| **Baby Meals** | LLM plans 5 meals → saves each via `save_meal_plan` |
| **Career Plan** | analyse applications → LLM suggests tasks → saves high-priority career tasks |
| **Study Plan** | read study tasks + prefs → LLM builds 7-day schedule → saves as tasks |
| **Business Notes** | paste sister call → LLM extracts decisions + action items → saves notes + tasks |
| **Weekly Review** | reads all done tasks + apps → LLM writes review → saves to notes |

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/ai-personal-assistant.git
cd ai-personal-assistant
pip install -r requirements.txt
```

### 2. Set your API key

```bash
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY or OPENAI_API_KEY
```

Or set it in the UI under **⚙️ Settings** after the app starts (key stays in memory, never sent to any server other than Anthropic/OpenAI).

### 3. Run

```bash
python run.py
# Open http://localhost:8000
```

### 4. Connect your calendar

Go to **⚙️ Settings → Calendar Reminders** for instructions. Subscribe to:
```
http://localhost:8000/calendar.ics
```
in Google Calendar, Apple Calendar, or Outlook to get push-notifications on your phone.

---

## 🧪 Tests

```bash
python -m pytest tests/ -v
# 12 tests, no API key needed
```

---

## 💬 Example chat prompts

```
"Plan my day for tomorrow"
"Add a study task: finish LangGraph tutorial, due Friday, high priority"
"What applications should I follow up on this week?"
"Plan baby's meals for today"
"I had a call with my sister — we decided to stock gold bangles for December, 
 she will handle procurement, I'll post on Instagram by Saturday"
"Remember that my wake time is 6:30 AM and I study best at night"
"Show me my weekly review"
```

---

## 🛠️ Tools the agent has access to

| Tool | Description |
|---|---|
| `get_current_time` | Current date/time in user's timezone |
| `get_summary` | Dashboard snapshot |
| `add_task` / `list_tasks` / `update_task` / `delete_task` | Full task CRUD |
| `add_event` / `list_events` / `delete_event` | Calendar with repeats + alarms |
| `remember_preference` / `list_preferences` / `forget_preference` | Long-term memory |
| `save_note` / `search_notes` | Topic notes (business calls, decisions) |
| `add_application` / `update_application` / `list_applications` / `delete_application` | Job tracker |
| `save_meal_plan` / `get_meal_plan` | Daily baby meals |

---

## 📦 Stack

- **Backend**: Python 3.11+, Starlette (FastAPI-compatible), Uvicorn
- **AI**: Anthropic Claude API or OpenAI API (HTTP calls, no heavy SDKs)
- **Storage**: SQLite (zero-config, single file)
- **Calendar**: RFC 5545 `.ics` with `VALARM` for push reminders
- **UI**: Vanilla JS single-page app, dark-mode, zero build step

---

## 📄 License

MIT — free to use, modify and share.


