"""Agent domain models - representing agents as 'people' with memory and judgment"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import NewType, Optional, List, Dict
from uuid import UUID, uuid4

AgentId = NewType("AgentId", UUID)


class AgentRole(str, Enum):
    """The role/profession of an agent in the company"""
    PM = "pm"                      # Product Manager
    ARCHITECT = "architect"        # Software Architect
    DEVELOPER = "developer"        # Developer
    TESTER = "tester"              # QA Tester
    
    @property
    def display_name(self) -> str:
        names = {
            AgentRole.PM: "Product Manager",
            AgentRole.ARCHITECT: "Architect",
            AgentRole.DEVELOPER: "Developer",
            AgentRole.TESTER: "Tester",
        }
        return names[self]


class AgentStatus(str, Enum):
    """Current working status of an agent"""
    WORKING = "working"    # 🟢 Actively processing a task
    WAITING = "waiting"    # 🟡 Blocked on external input
    IDLE = "idle"          # 🔵 No work in queue
    PAUSED = "paused"      # 🔴 Manually paused by human
    
    @property
    def emoji(self) -> str:
        emojis = {
            AgentStatus.WORKING: "🟢",
            AgentStatus.WAITING: "🟡",
            AgentStatus.IDLE: "🔵",
            AgentStatus.PAUSED: "🔴",
        }
        return emojis[self]


@dataclass
class Decision:
    """A decision made by an agent, stored in memory"""
    id: UUID = field(default_factory=uuid4)
    subject: str = ""
    choice: str = ""
    rationale: str = ""
    made_at: datetime = field(default_factory=datetime.utcnow)
    related_agents: List[AgentRole] = field(default_factory=list)


@dataclass
class Concern:
    """An active concern the agent is tracking"""
    id: UUID = field(default_factory=uuid4)
    description: str = ""
    severity: str = "medium"  # low, medium, high, critical
    raised_at: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False


@dataclass
class AgentMemory:
    """
    Persistent memory for an agent across the project.
    This is what makes an agent a 'person' rather than a stateless task executor.
    """
    # Understanding of the overall project
    project_context: str = ""
    
    # Past decisions and their rationale
    decision_history: List[Decision] = field(default_factory=list)
    
    # Things the agent is worried about or tracking
    active_concerns: List[Concern] = field(default_factory=list)
    
    # Trust/collaboration patterns with other agents
    # Maps agent_id -> notes about working relationship
    relationship_notes: Dict[str, str] = field(default_factory=dict)
    
    # What the agent has learned during the project
    learnings: List[str] = field(default_factory=list)
    
    def add_decision(self, subject: str, choice: str, rationale: str, 
                     related_agents: Optional[List[AgentRole]] = None) -> Decision:
        """Record a decision made by this agent"""
        decision = Decision(
            subject=subject,
            choice=choice,
            rationale=rationale,
            related_agents=related_agents or [],
        )
        self.decision_history.append(decision)
        return decision
    
    def add_concern(self, description: str, severity: str = "medium") -> Concern:
        """Flag something the agent is concerned about"""
        concern = Concern(description=description, severity=severity)
        self.active_concerns.append(concern)
        return concern
    
    def resolve_concern(self, concern_id: UUID) -> None:
        """Mark a concern as resolved"""
        for concern in self.active_concerns:
            if concern.id == concern_id:
                concern.resolved = True
                break
    
    def get_active_concerns(self) -> List[Concern]:
        """Get all unresolved concerns"""
        return [c for c in self.active_concerns if not c.resolved]
    
    def add_learning(self, learning: str) -> None:
        """Record something learned during the project"""
        self.learnings.append(learning)
    
    def update_relationship(self, agent_role: AgentRole, note: str) -> None:
        """Update notes about working relationship with another agent"""
        self.relationship_notes[agent_role.value] = note
    
    def get_context_summary(self) -> str:
        """Get a summary of the agent's current context for LLM prompts"""
        parts = []
        
        if self.project_context:
            parts.append(f"Project Context:\n{self.project_context}")
        
        if self.decision_history:
            recent = self.decision_history[-5:]  # Last 5 decisions
            decisions_text = "\n".join([
                f"- {d.subject}: {d.choice} (Reason: {d.rationale})"
                for d in recent
            ])
            parts.append(f"Recent Decisions:\n{decisions_text}")
        
        active = self.get_active_concerns()
        if active:
            concerns_text = "\n".join([
                f"- [{c.severity.upper()}] {c.description}"
                for c in active
            ])
            parts.append(f"Active Concerns:\n{concerns_text}")
        
        if self.learnings:
            recent_learnings = self.learnings[-3:]
            parts.append(f"Learnings:\n" + "\n".join(f"- {l}" for l in recent_learnings))
        
        return "\n\n".join(parts) if parts else "No context accumulated yet."


@dataclass
class AgentState:
    """
    Complete state of an agent at a point in time.
    This is what gets persisted and displayed on the dashboard.
    """
    id: AgentId = field(default_factory=lambda: AgentId(uuid4()))
    role: AgentRole = AgentRole.DEVELOPER
    status: AgentStatus = AgentStatus.IDLE
    
    # Persistent memory
    memory: AgentMemory = field(default_factory=AgentMemory)
    
    # Current work
    current_task_id: Optional[UUID] = None
    current_task_summary: str = ""
    
    # Why blocked (if status == WAITING)
    waiting_reason: Optional[str] = None
    
    # Queue sizes
    inbox_count: int = 0
    outbox_count: int = 0
    
    # Activity tracking
    last_activity: datetime = field(default_factory=datetime.utcnow)
    tasks_completed: int = 0
    
    # Sign-off status for convergence
    signed_off: bool = False
    signoff_blockers: List[str] = field(default_factory=list)
    
    def update_status(self, status: AgentStatus, reason: Optional[str] = None) -> None:
        """Update agent status and clear/set waiting reason"""
        self.status = status
        self.waiting_reason = reason if status == AgentStatus.WAITING else None
        self.last_activity = datetime.utcnow()
    
    def start_task(self, task_id: UUID, summary: str) -> None:
        """Mark that agent is starting work on a task"""
        self.current_task_id = task_id
        self.current_task_summary = summary
        self.status = AgentStatus.WORKING
        self.last_activity = datetime.utcnow()
    
    def complete_task(self) -> None:
        """Mark current task as complete"""
        self.current_task_id = None
        self.current_task_summary = ""
        self.tasks_completed += 1
        self.last_activity = datetime.utcnow()
    
    def sign_off(self) -> None:
        """Agent signs off that their domain is complete"""
        if self.signoff_blockers:
            raise ValueError(f"Cannot sign off with blockers: {self.signoff_blockers}")
        self.signed_off = True
    
    def revoke_signoff(self, reason: str) -> None:
        """Revoke signoff due to new issue"""
        self.signed_off = False
        self.signoff_blockers.append(reason)
    
    def clear_blocker(self, blocker: str) -> None:
        """Clear a signoff blocker"""
        if blocker in self.signoff_blockers:
            self.signoff_blockers.remove(blocker)
