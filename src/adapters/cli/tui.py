from __future__ import annotations
"""Interactive Terminal UI Dashboard using Textual"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, DataTable, Input, Label, Button, Log
from textual.binding import Binding
from textual.reactive import reactive
from textual.message import Message as TextualMessage
from textual import work

from rich.text import Text
from rich.panel import Panel
from rich.table import Table

from ...core.models import Project, AgentRole, AgentStatus, Message, Task
from ...runtime.status import DashboardData, StatusAggregator


class AgentStatusWidget(Static):
    """Widget displaying status of all agents"""
    
    def __init__(self, project: Project, **kwargs):
        super().__init__(**kwargs)
        self.project = project
        self.status = StatusAggregator(project)
    
    def compose(self) -> ComposeResult:
        yield DataTable(id="agent-table")
    
    def on_mount(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.add_columns("Agent", "Status", "Current Work", "Inbox", "Done", "✓")
        self.refresh_data()
    
    def refresh_data(self) -> None:
        """Refresh the agent status table"""
        table = self.query_one("#agent-table", DataTable)
        table.clear()
        
        for role, agent in self.project.agents.items():
            status_emoji = agent.status.emoji
            work = agent.current_task_summary or "Idle"
            if agent.waiting_reason:
                work = f"⏳ {agent.waiting_reason}"
            if len(work) > 35:
                work = work[:32] + "..."
            
            signoff = "✓" if agent.signed_off else ""
            
            table.add_row(
                role.display_name,
                f"{status_emoji} {agent.status.value}",
                work,
                str(agent.inbox_count),
                str(agent.tasks_completed),
                signoff,
            )


class ActivityLogWidget(Static):
    """Widget displaying recent activity"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._messages: list[Message] = []
    
    def compose(self) -> ComposeResult:
        yield Log(id="activity-log", highlight=True, max_lines=100)
    
    def add_message(self, msg: Message) -> None:
        """Add a message to the activity log"""
        self._messages.append(msg)
        log = self.query_one("#activity-log", Log)
        
        # Handle both naive and aware datetimes
        try:
            now = datetime.now(timezone.utc)
            timestamp = msg.timestamp
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            time_ago = now - timestamp
            seconds = time_ago.total_seconds()
            if seconds < 60:
                time_str = f"{int(seconds)}s"
            else:
                time_str = f"{int(seconds // 60)}m"
        except (TypeError, AttributeError):
            time_str = "now"
        
        log.write_line(f"[dim]{time_str}[/] [cyan]{msg.from_agent} → {msg.to_agent}[/]: {msg.summary}")
    
    def add_system_message(self, text: str, style: str = "yellow") -> None:
        """Add a system message"""
        log = self.query_one("#activity-log", Log)
        log.write_line(f"[{style}]▶ {text}[/]")


class MetricsWidget(Static):
    """Widget displaying project metrics"""
    
    tasks_completed = reactive(0)
    pending_tasks = reactive(0)
    blockers = reactive(0)
    signoff_progress = reactive("0/4")
    
    def render(self) -> Text:
        text = Text()
        text.append("📊 ", style="bold")
        text.append(f"Done: {self.tasks_completed}", style="green")
        text.append(" | ", style="dim")
        text.append(f"Pending: {self.pending_tasks}", style="yellow")
        text.append(" | ", style="dim")
        text.append(f"Blockers: {self.blockers}", style="red" if self.blockers > 0 else "dim")
        text.append(" | ", style="dim")
        text.append(f"Signoff: {self.signoff_progress}", style="blue")
        return text


class ProjectHeaderWidget(Static):
    """Widget displaying project header info"""
    
    project_name = reactive("AI Company Project")
    project_state = reactive("created")
    elapsed_time = reactive("0m 0s")
    
    def render(self) -> Text:
        text = Text()
        text.append(f"📋 {self.project_name}", style="bold cyan")
        text.append("  |  State: ", style="dim")
        text.append(self.project_state, style="yellow")
        text.append("  |  Elapsed: ", style="dim")
        text.append(self.elapsed_time, style="green")
        return text


class ClarificationModal(Static):
    """Widget for handling clarification requests"""
    
    def __init__(self, question: str, on_submit: Callable[[str], None], **kwargs):
        super().__init__(**kwargs)
        self.question = question
        self.on_submit = on_submit
    
    def compose(self) -> ComposeResult:
        yield Label(f"[bold yellow]📝 Clarification Needed[/]", id="clarification-title")
        yield Label(self.question, id="clarification-question")
        yield Input(placeholder="Type your answer...", id="clarification-input")
        yield Horizontal(
            Button("Submit", variant="primary", id="submit-btn"),
            Button("Skip", variant="default", id="skip-btn"),
            id="clarification-buttons"
        )
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            input_widget = self.query_one("#clarification-input", Input)
            self.on_submit(input_widget.value)
            self.remove()
        elif event.button.id == "skip-btn":
            self.on_submit("")
            self.remove()
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.on_submit(event.value)
        self.remove()


class AICompanyApp(App):
    """Main AI Company Terminal UI Application"""
    
    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto auto;
    }
    
    #header-container {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }
    
    #main-container {
        layout: grid;
        grid-size: 2;
        grid-columns: 1fr 1fr;
        padding: 1;
    }
    
    #agents-panel {
        border: solid $primary;
        padding: 1;
        height: 100%;
    }
    
    #activity-panel {
        border: solid $accent;
        padding: 1;
        height: 100%;
    }
    
    #metrics-container {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
    }
    
    #agent-table {
        height: 100%;
    }
    
    #activity-log {
        height: 100%;
    }
    
    .panel-title {
        text-style: bold;
        color: $text;
        padding-bottom: 1;
    }
    
    ClarificationModal {
        layer: dialog;
        padding: 1 2;
        background: $surface;
        border: tall $warning;
        width: 60%;
        height: auto;
        margin: 4 8;
    }
    
    #clarification-title {
        padding-bottom: 1;
    }
    
    #clarification-question {
        padding-bottom: 1;
        color: $text;
    }
    
    #clarification-input {
        margin-bottom: 1;
    }
    
    #clarification-buttons {
        align: center middle;
    }
    
    #clarification-buttons Button {
        margin: 0 1;
    }
    """
    
    BINDINGS = [
        Binding("p", "pause", "Pause"),
        Binding("r", "resume", "Resume"),
        Binding("i", "inject", "Inject Guidance"),
        Binding("s", "status", "Status"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]
    
    def __init__(
        self,
        project: Project,
        on_pause: Optional[Callable[[], Awaitable[None]]] = None,
        on_resume: Optional[Callable[[], Awaitable[None]]] = None,
        on_inject: Optional[Callable[[str], Awaitable[None]]] = None,
        on_quit: Optional[Callable[[], Awaitable[None]]] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.project = project
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_inject = on_inject
        self._on_quit = on_quit
        self._session_start_time = datetime.now(timezone.utc)  # Renamed to avoid conflict with Textual's _start_time
        self._pending_clarification: Optional[tuple[Task, Callable[[str], None]]] = None
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with Container(id="header-container"):
            yield ProjectHeaderWidget(id="project-header")
        
        with Container(id="main-container"):
            with Vertical(id="agents-panel"):
                yield Label("👥 Agent Status", classes="panel-title")
                yield AgentStatusWidget(self.project, id="agent-status")
            
            with Vertical(id="activity-panel"):
                yield Label("📜 Activity Log", classes="panel-title")
                yield ActivityLogWidget(id="activity-log-widget")
        
        with Container(id="metrics-container"):
            yield MetricsWidget(id="metrics")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Start the update loop when mounted"""
        self.title = "🏢 AI Company"
        self.sub_title = self.project.name
        self._update_header()
        self.set_interval(1.0, self._refresh_display)
    
    def _update_header(self) -> None:
        """Update header information"""
        header = self.query_one("#project-header", ProjectHeaderWidget)
        header.project_name = self.project.name
        header.project_state = self.project.state.value
        
        elapsed = datetime.now(timezone.utc) - self._session_start_time
        mins = int(elapsed.total_seconds() // 60)
        secs = int(elapsed.total_seconds() % 60)
        header.elapsed_time = f"{mins}m {secs}s"
    
    def _refresh_display(self) -> None:
        """Refresh all display elements"""
        self._update_header()
        
        # Update agent status
        agent_widget = self.query_one("#agent-status", AgentStatusWidget)
        agent_widget.refresh_data()
        
        # Update metrics
        metrics = self.query_one("#metrics", MetricsWidget)
        total_completed = sum(a.tasks_completed for a in self.project.agents.values())
        total_inbox = sum(a.inbox_count for a in self.project.agents.values())
        blockers = len([a for a in self.project.agents.values() if a.status == AgentStatus.WAITING])
        signed_off = len([a for a in self.project.agents.values() if a.signed_off])
        
        metrics.tasks_completed = total_completed
        metrics.pending_tasks = total_inbox
        metrics.blockers = blockers
        metrics.signoff_progress = f"{signed_off}/{len(self.project.agents)}"
    
    def add_activity(self, message: Message) -> None:
        """Add a message to the activity log"""
        try:
            activity = self.query_one("#activity-log-widget", ActivityLogWidget)
            activity.add_message(message)
        except Exception:
            pass  # Widget may not be mounted yet
    
    def add_system_message(self, text: str, style: str = "yellow") -> None:
        """Add a system message to the activity log"""
        try:
            activity = self.query_one("#activity-log-widget", ActivityLogWidget)
            activity.add_system_message(text, style)
        except Exception:
            pass
    
    def request_clarification(self, task: Task, callback: Callable[[str], None]) -> None:
        """Show clarification modal"""
        self._pending_clarification = (task, callback)
        
        def on_submit(answer: str):
            callback(answer)
            self._pending_clarification = None
        
        modal = ClarificationModal(task.content, on_submit)
        self.mount(modal)
    
    async def action_pause(self) -> None:
        """Pause all agents"""
        self.add_system_message("Pausing all agents...", "yellow")
        if self._on_pause:
            await self._on_pause()
        self.add_system_message("All agents paused", "yellow")
    
    async def action_resume(self) -> None:
        """Resume all agents"""
        self.add_system_message("Resuming all agents...", "green")
        if self._on_resume:
            await self._on_resume()
        self.add_system_message("All agents resumed", "green")
    
    async def action_inject(self) -> None:
        """Inject guidance"""
        def on_submit(guidance: str):
            if guidance and self._on_inject:
                self.call_later(lambda: asyncio.create_task(self._on_inject(guidance)))
                self.add_system_message(f"Guidance injected: {guidance}", "cyan")
        
        modal = ClarificationModal(
            "Enter guidance for all agents:",
            on_submit
        )
        self.mount(modal)
    
    def action_status(self) -> None:
        """Show detailed status"""
        status = []
        for role, agent in self.project.agents.items():
            status.append(f"{agent.status.emoji} {role.display_name}: {agent.current_task_summary or 'Idle'}")
        
        self.add_system_message("\n".join(status), "blue")
    
    async def action_quit(self) -> None:
        """Quit the application"""
        if self._on_quit:
            await self._on_quit()
        self.exit()
    
    def show_delivered(self, output_files: list[str]) -> None:
        """Show delivery complete message"""
        self.add_system_message("=" * 50, "green")
        self.add_system_message("✅ PROJECT DELIVERED!", "bold green")
        self.add_system_message(f"Files created: {len(output_files)}", "green")
        for f in output_files[:5]:
            self.add_system_message(f"  📄 {f}", "green")
        if len(output_files) > 5:
            self.add_system_message(f"  ... and {len(output_files) - 5} more", "green")
        self.add_system_message("=" * 50, "green")


async def run_tui(
    project: Project,
    on_pause: Optional[Callable[[], Awaitable[None]]] = None,
    on_resume: Optional[Callable[[], Awaitable[None]]] = None,
    on_inject: Optional[Callable[[str], Awaitable[None]]] = None,
    on_quit: Optional[Callable[[], Awaitable[None]]] = None,
) -> AICompanyApp:
    """Create and return the TUI app instance"""
    app = AICompanyApp(
        project=project,
        on_pause=on_pause,
        on_resume=on_resume,
        on_inject=on_inject,
        on_quit=on_quit,
    )
    return app
