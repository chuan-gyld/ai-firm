# 🏢 AI Company

An AI-powered "company" that autonomously builds products from your ideas.

## Overview

AI Company takes your product idea and autonomously:
1. **PM** refines requirements, creates user stories
2. **Architect** designs the system, chooses patterns  
3. **Developer** writes the code
4. **Tester** tests it, finds bugs → triggers loops back to Dev/Architect
5. Agents iterate until all sign off → **delivers working code**

You only interact for:
- **Clarification**: When agents need more info from you
- **Verification**: When agents need your approval at milestones

## Key Features

- **Agents as People**: Each agent has persistent memory, judgment, and can push back
- **Closed Feedback Loops**: Not linear - bugs flow back through the system
- **Async Processing**: Agents work concurrently, tasks flow through prioritized inboxes
- **Real-time Dashboard**: See what every agent is doing at any time
- **No Artificial Limits**: You control via visibility and intervention, not arbitrary loop breakers

## Installation

```bash
# Clone the repository
git clone https://github.com/chuan-gyld/ai-firm.git
cd ai-firm

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .
```

## Configuration

Set your API key (default uses Zhipu AI GLM-4):
```bash
# For Zhipu GLM models (default)
export ZHIPU_API_KEY='your-key'
# Get your API key from: https://open.bigmodel.cn/

# Alternative: For Claude models
export ANTHROPIC_API_KEY='your-key'

# Alternative: For OpenAI models
export OPENAI_API_KEY='your-key'
```

Configure in `config/settings.yaml`:
```yaml
llm:
  # Default: Zhipu GLM-4 Plus
  model: "openai/glm-4-plus"
  api_base: "https://open.bigmodel.cn/api/paas/v4"
  
  # Alternative models:
  # model: "openai/glm-4"           # Zhipu GLM-4
  # model: "openai/glm-4-flash"     # Zhipu GLM-4 Flash (faster)
  # model: "claude-sonnet-4-20250514"  # Claude (requires ANTHROPIC_API_KEY)
  # model: "gpt-4o"                 # OpenAI (requires OPENAI_API_KEY)
  
  temperature: 0.7
  max_tokens: 4096
```

## Usage

### Run with an idea

```bash
# With uv
uv run python -m src.main "Build a CLI todo app with SQLite persistence"

# Or with activated venv
python -m src.main "Build a CLI todo app with SQLite persistence"
```

### Interactive prompt

```bash
uv run python -m src.main
# Then enter your idea when prompted
```

### What happens

1. **Interactive TUI dashboard** appears showing real-time agent status
2. **Agents work autonomously** - PM creates requirements, Architect designs, Developer codes
3. **You get asked for clarification** if agents need more info (modal dialog in TUI)
4. **You approve milestones** when agents complete major phases
5. **Output is delivered** to `./output/<project-id>/`

### Keyboard Controls

| Key | Action |
|-----|--------|
| `p` | Pause all agents |
| `r` | Resume all agents |
| `i` | Inject guidance (opens input dialog) |
| `s` | Show detailed status |
| `q` | Quit |

## Interactive Dashboard

The AI Company features a fully interactive terminal UI built with Textual:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 🏢 AI Company                                                    12:34:56 PM │
├──────────────────────────────────────────────────────────────────────────────┤
│ 📋 CLI Todo App  |  State: implementation  |  Elapsed: 5m 23s               │
├────────────────────────────────┬─────────────────────────────────────────────┤
│ 👥 Agent Status                │ 📜 Activity Log                            │
│ ┌────────────────────────────┐ │ ┌─────────────────────────────────────────┐ │
│ │ Agent     Status  Work     │ │ │ 2m  pm → architect: Requirements Ready │ │
│ │ ───────────────────────────│ │ │ 1m  architect → dev: Design Complete   │ │
│ │ PM        🟢 Done  ✓       │ │ │ 30s developer: Implementing auth...    │ │
│ │ Architect 🟢 Done  ✓       │ │ │ 10s dev → tester: Code ready for test  │ │
│ │ Developer 🟢 Working       │ │ │ ▶ Starting AI Company with idea...     │ │
│ │ Tester    🔵 Idle          │ │ └─────────────────────────────────────────┘ │
│ └────────────────────────────┘ │                                             │
├────────────────────────────────┴─────────────────────────────────────────────┤
│ 📊 Done: 12 | Pending: 3 | Blockers: 0 | Signoff: 2/4                        │
├──────────────────────────────────────────────────────────────────────────────┤
│ p Pause  r Resume  i Inject  s Status  q Quit                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Features

- **Real-time updates**: Agent status and activity log update live
- **Interactive controls**: Pause, resume, inject guidance via keyboard
- **Clarification modals**: When agents need input, a dialog appears
- **Activity log**: See all inter-agent communication in real-time
- **Metrics bar**: Track completed tasks, pending work, and blockers

📝 Clarification Needed
From: pm

Do you want priority levels (high/medium/low) for tasks?

Your answer: yes

... agents continue working ...

✅ Project Delivered!

Project: CLI Todo App
Files: 5 created
Output: ./output/abc123/

Generated Files:
  📄 todo.py
  📄 db.py
  📄 models.py
  📄 docs/requirements.md
  📄 docs/design.md
```

## Architecture

```
src/
├── core/               # Pure business logic (no deps)
│   ├── models/         # Agent, Task, Artifact, Project
│   ├── ports/          # LLM, Storage interfaces
│   └── services/       # Domain services
│
├── agents/             # AI team members
│   ├── base.py         # Common agent logic
│   ├── pm.py           # Product Manager
│   ├── architect.py    # Software Architect
│   ├── developer.py    # Developer
│   ├── tester.py       # QA Tester
│   └── prompts/        # Role-specific prompts
│
├── runtime/            # Async execution
│   ├── loop.py         # Agent runtime manager
│   ├── queue.py        # Priority inbox/outbox
│   └── status.py       # Dashboard data
│
├── adapters/           # External integrations
│   ├── llm_litellm.py  # LLM adapter (Claude/GPT)
│   ├── storage_sqlite.py
│   └── cli/            # Terminal interface
│
└── main.py             # Entry point
```

## How Agents Work

Each agent is modeled as a "person" with:

- **Persistent Memory**: Remembers decisions, concerns, learnings
- **Prioritized Inbox**: Async task queue
- **Judgment**: Can accept, reject, or counter-propose requests
- **Owned Artifacts**: Documents they create and maintain

Agents communicate directly with each other (peer-to-peer), not through a central orchestrator.

## Human Interaction Points

### 1. Clarification
When an agent needs more info:
```
📝 Clarification Needed
From: pm

Should the todo app support multiple users?

Your answer: No, single user only
```

### 2. Milestone Verification
When a phase is complete:
```
🏁 Milestone Reached: Design Complete

Technical design is ready for implementation.

Approve this milestone? [Y/n]: y
```

## Dashboard Commands

While running, you can:
- `p` - Pause all agents
- `r` - Resume agents
- `i` - Inject guidance ("Focus on MVP")
- `s` - Show status summary
- `q` - Quit

## Configuration Options

`config/settings.yaml`:

```yaml
llm:
  model: "claude-sonnet-4-20250514"
  fallback_model: "gpt-4o"
  temperature: 0.7
  max_tokens: 4096

agents:
  idle_poll_interval: 0.5
  max_wip: 1

project:
  output_dir: "./output"
  state_db: "./state.db"

dashboard:
  refresh_interval: 1.0
  recent_activity_limit: 10
```

## Development

```bash
# Install with dev dependencies
uv sync

# Run tests
uv run pytest

# Lint
uv run ruff check src/

# Format
uv run ruff format src/
```

## License

MIT
