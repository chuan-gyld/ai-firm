from __future__ import annotations
"""Terminal Dashboard - real-time status display using Rich"""

import asyncio
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text

from ...core.models import Project, AgentRole, AgentStatus, Message
from ...runtime.status import DashboardData, StatusAggregator


class TerminalDashboard:
    """
    Rich-based terminal dashboard for monitoring the AI Company.
    """
    
    def __init__(self, project: Project):
        self.project = project
        self.console = Console()
        self.status = StatusAggregator(project)
        self._recent_activity: list[Message] = []
        self._running = False
    
    def render_dashboard(self, data: Optional[DashboardData] = None) -> Panel:
        """Render the complete dashboard as a Rich Panel"""
        if data is None:
            data = self.status.get_dashboard_data(self._recent_activity)
        
        layout = Layout()
        
        # Create sections
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="agents", size=8),
            Layout(name="activity", size=10),
            Layout(name="footer", size=3),
        )
        
        # Header
        header = self._render_header(data)
        layout["header"].update(header)
        
        # Agent status table
        agent_table = self._render_agent_table(data)
        layout["agents"].update(Panel(agent_table, title="Agent Status"))
        
        # Recent activity
        activity = self._render_activity(data)
        layout["activity"].update(Panel(activity, title="Recent Activity"))
        
        # Footer with commands
        footer = self._render_footer(data)
        layout["footer"].update(footer)
        
        return Panel(layout, title="🏢 AI Company Dashboard", border_style="blue")
    
    def _render_header(self, data: DashboardData) -> Panel:
        """Render the header section"""
        elapsed = datetime.utcnow() - data.started_at
        elapsed_str = f"{int(elapsed.total_seconds() // 60)}m {int(elapsed.total_seconds() % 60)}s"
        
        last_activity = datetime.utcnow() - data.last_activity
        last_str = f"{int(last_activity.total_seconds())}s ago"
        
        text = Text()
        text.append(f"📋 {data.project_name}", style="bold cyan")
        text.append(f"  |  State: ", style="dim")
        text.append(f"{data.project_state}", style="yellow")
        text.append(f"  |  Elapsed: ", style="dim")
        text.append(elapsed_str, style="green")
        text.append(f"  |  Last: ", style="dim")
        text.append(last_str, style="blue")
        
        return Panel(text, style="dim")
    
    def _render_agent_table(self, data: DashboardData) -> Table:
        """Render the agent status table"""
        table = Table(show_header=True, header_style="bold magenta", expand=True)
        
        table.add_column("Agent", style="cyan", width=12)
        table.add_column("Status", width=10)
        table.add_column("Current Work", width=35)
        table.add_column("Inbox", justify="right", width=6)
        table.add_column("Done", justify="right", width=5)
        table.add_column("✓", justify="center", width=3)
        
        for agent in data.agents:
            status_style = {
                AgentStatus.WORKING: "green",
                AgentStatus.WAITING: "yellow",
                AgentStatus.IDLE: "blue",
                AgentStatus.PAUSED: "red",
            }.get(agent.status, "white")
            
            work = agent.current_work
            if agent.waiting_reason:
                work = f"⏳ {agent.waiting_reason}"
            
            if len(work) > 33:
                work = work[:30] + "..."
            
            signoff = "✓" if agent.signed_off else ""
            
            table.add_row(
                agent.role.display_name,
                Text(f"{agent.status_emoji} {agent.status.value}", style=status_style),
                work,
                str(agent.inbox_count),
                str(agent.tasks_completed),
                Text(signoff, style="green"),
            )
        
        return table
    
    def _render_activity(self, data: DashboardData) -> Table:
        """Render recent activity"""
        table = Table(show_header=False, expand=True, box=None)
        table.add_column("Time", width=6)
        table.add_column("Flow", width=20)
        table.add_column("Summary", width=50)
        
        for msg in reversed(data.recent_activity[-8:]):
            time_ago = datetime.utcnow() - msg.timestamp
            if time_ago.total_seconds() < 60:
                time_str = f"{int(time_ago.total_seconds())}s"
            else:
                time_str = f"{int(time_ago.total_seconds() // 60)}m"
            
            flow = f"{msg.from_agent} → {msg.to_agent}"
            
            summary = msg.summary
            if len(summary) > 48:
                summary = summary[:45] + "..."
            
            table.add_row(
                Text(time_str, style="dim"),
                Text(flow, style="cyan"),
                summary,
            )
        
        if not data.recent_activity:
            table.add_row("", "", Text("No activity yet...", style="dim italic"))
        
        return table
    
    def _render_footer(self, data: DashboardData) -> Panel:
        """Render footer with metrics and commands"""
        text = Text()
        text.append(f"📊 ", style="bold")
        text.append(f"Tasks: {data.total_tasks_completed} done", style="green")
        text.append(f"  |  ", style="dim")
        text.append(f"Pending: {data.pending_tasks}", style="yellow")
        text.append(f"  |  ", style="dim")
        text.append(f"Blockers: {data.blockers}", style="red" if data.blockers > 0 else "dim")
        text.append(f"  |  ", style="dim")
        text.append(data.signoff_progress, style="blue")
        
        text.append("\n")
        text.append("Commands: ", style="dim")
        text.append("[p]", style="bold yellow")
        text.append("ause ", style="dim")
        text.append("[r]", style="bold green")
        text.append("esume ", style="dim")
        text.append("[i]", style="bold cyan")
        text.append("nject ", style="dim")
        text.append("[s]", style="bold blue")
        text.append("tatus ", style="dim")
        text.append("[q]", style="bold red")
        text.append("uit", style="dim")
        
        return Panel(text, style="dim")
    
    def print_status(self) -> None:
        """Print a one-time status update"""
        panel = self.render_dashboard()
        self.console.print(panel)
    
    def print_summary(self) -> None:
        """Print a concise summary"""
        summary = self.status.get_summary()
        self.console.print(Panel(summary, title="Status Summary", border_style="blue"))
    
    def add_activity(self, message: Message) -> None:
        """Add a message to the activity log"""
        self._recent_activity.append(message)
        # Keep only last 50
        self._recent_activity = self._recent_activity[-50:]
    
    async def run_live(self, refresh_rate: float = 1.0) -> None:
        """Run a live-updating dashboard"""
        self._running = True
        
        with Live(self.render_dashboard(), refresh_per_second=1/refresh_rate, console=self.console) as live:
            while self._running:
                live.update(self.render_dashboard())
                await asyncio.sleep(refresh_rate)
    
    def stop(self) -> None:
        """Stop the live dashboard"""
        self._running = False


def print_welcome(console: Console) -> None:
    """Print welcome message"""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]🏢 AI Company[/bold cyan]\n"
        "[dim]Autonomous Product Realization System[/dim]",
        border_style="blue",
    ))
    console.print()


def print_delivered(console: Console, project: Project, output_files: list[str]) -> None:
    """Print delivery summary"""
    console.print()
    console.print(Panel.fit(
        f"[bold green]✅ Project Delivered![/bold green]\n\n"
        f"[cyan]Project:[/cyan] {project.name}\n"
        f"[cyan]Files:[/cyan] {len(output_files)} created\n"
        f"[cyan]Output:[/cyan] {project.output_directory}",
        title="🎉 Success",
        border_style="green",
    ))
    
    if output_files:
        console.print("\n[bold]Generated Files:[/bold]")
        for f in output_files[:10]:
            console.print(f"  📄 {f}")
        if len(output_files) > 10:
            console.print(f"  ... and {len(output_files) - 10} more")
    
    console.print()
