from __future__ import annotations
"""Status Aggregator - collects and summarizes agent status for dashboard"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..core.models import Project, AgentRole, AgentStatus, Message


@dataclass
class AgentStatusRow:
    """Status row for dashboard display"""
    role: AgentRole
    status: AgentStatus
    status_emoji: str
    current_work: str
    waiting_reason: Optional[str]
    inbox_count: int
    tasks_completed: int
    signed_off: bool


@dataclass
class DashboardData:
    """Complete dashboard snapshot"""
    project_name: str
    project_state: str
    started_at: datetime
    last_activity: datetime
    
    # Agent status table
    agents: list[AgentStatusRow]
    
    # Recent activity
    recent_activity: list[Message]
    
    # Metrics
    total_tasks_completed: int
    pending_tasks: int
    blockers: int
    
    # Convergence
    signoff_progress: str  # e.g., "2/4 agents signed off"


class StatusAggregator:
    """
    Aggregates status from all agents for dashboard display.
    """
    
    def __init__(self, project: Project):
        self.project = project
    
    def get_dashboard_data(self, recent_activity: list[Message] | None = None) -> DashboardData:
        """Generate dashboard snapshot"""
        agents = self._get_agent_rows()
        
        # Calculate metrics
        total_completed = sum(a.tasks_completed for a in agents)
        pending = sum(a.inbox_count for a in agents)
        blockers = len([a for a in agents if a.status == AgentStatus.WAITING])
        
        # Convergence progress
        signed_off = len([a for a in agents if a.signed_off])
        signoff_progress = f"{signed_off}/{len(agents)} agents signed off"
        
        # Last activity
        last_activity = max(
            (self.project.agents[a.role].last_activity for a in agents),
            default=datetime.utcnow()
        )
        
        return DashboardData(
            project_name=self.project.name,
            project_state=self.project.state.value,
            started_at=self.project.created_at,
            last_activity=last_activity,
            agents=agents,
            recent_activity=recent_activity or self.project.get_recent_activity(10),
            total_tasks_completed=total_completed,
            pending_tasks=pending,
            blockers=blockers,
            signoff_progress=signoff_progress,
        )
    
    def _get_agent_rows(self) -> list[AgentStatusRow]:
        """Get status rows for all agents"""
        rows = []
        for role, agent in self.project.agents.items():
            rows.append(AgentStatusRow(
                role=role,
                status=agent.status,
                status_emoji=agent.status.emoji,
                current_work=agent.current_task_summary or "Idle",
                waiting_reason=agent.waiting_reason,
                inbox_count=agent.inbox_count,
                tasks_completed=agent.tasks_completed,
                signed_off=agent.signed_off,
            ))
        return rows
    
    def get_summary(self) -> str:
        """Get a concise text summary"""
        agents = self._get_agent_rows()
        
        working = [a for a in agents if a.status == AgentStatus.WORKING]
        waiting = [a for a in agents if a.status == AgentStatus.WAITING]
        idle = [a for a in agents if a.status == AgentStatus.IDLE]
        
        lines = [
            f"📊 Status: {len(working)} working, {len(waiting)} waiting, {len(idle)} idle",
        ]
        
        if waiting:
            lines.append("⏳ Blockers:")
            for a in waiting:
                lines.append(f"  • {a.role.display_name}: {a.waiting_reason or 'Unknown'}")
        
        # Recent decisions from memory
        recent_decisions = []
        for role, agent in self.project.agents.items():
            if agent.memory.decision_history:
                last = agent.memory.decision_history[-1]
                recent_decisions.append((last.made_at, role, last.subject, last.choice))
        
        if recent_decisions:
            recent_decisions.sort(reverse=True)
            lines.append("🔄 Recent Decisions:")
            for _, role, subject, choice in recent_decisions[:3]:
                lines.append(f"  • {role.display_name}: {subject} → {choice}")
        
        return "\n".join(lines)
    
    def get_convergence_status(self) -> dict:
        """Get detailed convergence status"""
        status = {}
        for role, agent in self.project.agents.items():
            status[role] = {
                "signed_off": agent.signed_off,
                "blockers": agent.signoff_blockers,
            }
        
        return {
            "all_signed_off": self.project.all_agents_signed_off(),
            "agents": status,
        }
