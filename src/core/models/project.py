from __future__ import annotations
"""Project domain models - the overall project being built"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import NewType, Optional
from uuid import UUID, uuid4

from .agent import AgentRole, AgentState
from .artifact import Artifact, ArtifactId
from .task import Task, TaskId, Message

ProjectId = NewType("ProjectId", UUID)


class ProjectState(str, Enum):
    """High-level state of the project"""
    CREATED = "created"              # Just started
    DISCOVERY = "discovery"          # PM refining requirements
    DESIGN = "design"                # Architect designing
    IMPLEMENTATION = "implementation"  # Developer coding
    TESTING = "testing"              # Tester testing
    REVIEW = "review"                # Final review
    AWAITING_INPUT = "awaiting_input"  # Waiting for human
    DELIVERED = "delivered"          # Done!
    PAUSED = "paused"                # Manually paused
    FAILED = "failed"                # Something went wrong
    
    @property
    def emoji(self) -> str:
        emojis = {
            ProjectState.CREATED: "🆕",
            ProjectState.DISCOVERY: "🔍",
            ProjectState.DESIGN: "📐",
            ProjectState.IMPLEMENTATION: "💻",
            ProjectState.TESTING: "🧪",
            ProjectState.REVIEW: "👀",
            ProjectState.AWAITING_INPUT: "⏳",
            ProjectState.DELIVERED: "✅",
            ProjectState.PAUSED: "⏸️",
            ProjectState.FAILED: "❌",
        }
        return emojis[self]


@dataclass
class Milestone:
    """A milestone that requires human verification"""
    id: UUID = field(default_factory=uuid4)
    name: str = ""
    description: str = ""
    reached_at: Optional[datetime] = None
    approved: bool = False
    approved_at: Optional[datetime] = None
    human_feedback: Optional[str] = None
    artifacts: list[ArtifactId] = field(default_factory=list)


@dataclass
class Project:
    """
    The complete project state including all agents, artifacts, and history.
    This is the central data structure for the AI Company.
    """
    id: ProjectId = field(default_factory=lambda: ProjectId(uuid4()))
    
    # Project info
    name: str = ""
    original_idea: str = ""
    refined_description: str = ""
    
    # State
    state: ProjectState = ProjectState.CREATED
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Agents
    agents: dict[AgentRole, AgentState] = field(default_factory=dict)
    
    # Artifacts
    artifacts: dict[ArtifactId, Artifact] = field(default_factory=dict)
    
    # Task history
    task_history: list[Task] = field(default_factory=list)
    
    # Message log for activity feed
    activity_log: list[Message] = field(default_factory=list)
    
    # Milestones
    milestones: list[Milestone] = field(default_factory=list)
    current_milestone: Optional[Milestone] = None
    
    # Human interaction
    pending_clarification: Optional[Task] = None
    pending_verification: Optional[Milestone] = None
    
    # Output
    output_directory: str = ""
    
    def initialize_agents(self) -> None:
        """Create initial agent states for all roles"""
        for role in AgentRole:
            self.agents[role] = AgentState(role=role)
    
    def get_agent(self, role: AgentRole) -> AgentState:
        """Get agent state by role"""
        return self.agents.get(role)
    
    def update_state(self, new_state: ProjectState) -> None:
        """Update project state"""
        self.state = new_state
        self.updated_at = datetime.utcnow()
    
    def add_artifact(self, artifact: Artifact) -> None:
        """Add an artifact to the project"""
        self.artifacts[artifact.id] = artifact
        self.updated_at = datetime.utcnow()
    
    def get_artifacts_by_type(self, artifact_type) -> list[Artifact]:
        """Get all artifacts of a specific type"""
        return [a for a in self.artifacts.values() if a.artifact_type == artifact_type]
    
    def get_artifacts_by_owner(self, owner: AgentRole) -> list[Artifact]:
        """Get all artifacts owned by a specific agent"""
        return [a for a in self.artifacts.values() if a.owner == owner]
    
    def log_activity(self, task: Task) -> None:
        """Add a task to the activity log"""
        message = Message.from_task(task)
        self.activity_log.append(message)
        self.task_history.append(task)
    
    def get_recent_activity(self, limit: int = 10) -> list[Message]:
        """Get recent activity messages"""
        return self.activity_log[-limit:]
    
    def all_agents_signed_off(self) -> bool:
        """Check if all agents have signed off for convergence"""
        return all(agent.signed_off for agent in self.agents.values())
    
    def get_signoff_status(self) -> dict[AgentRole, tuple[bool, list[str]]]:
        """Get sign-off status for each agent"""
        return {
            role: (agent.signed_off, agent.signoff_blockers)
            for role, agent in self.agents.items()
        }
    
    def mark_delivered(self) -> None:
        """Mark project as delivered"""
        self.state = ProjectState.DELIVERED
        self.completed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def create_milestone(self, name: str, description: str) -> Milestone:
        """Create a new milestone"""
        milestone = Milestone(
            name=name,
            description=description,
            reached_at=datetime.utcnow(),
        )
        self.milestones.append(milestone)
        self.current_milestone = milestone
        self.pending_verification = milestone
        return milestone
    
    def approve_milestone(self, feedback: str | None = None) -> None:
        """Approve the current milestone"""
        if self.current_milestone:
            self.current_milestone.approved = True
            self.current_milestone.approved_at = datetime.utcnow()
            self.current_milestone.human_feedback = feedback
            self.pending_verification = None
    
    def reject_milestone(self, feedback: str) -> None:
        """Reject the current milestone with feedback"""
        if self.current_milestone:
            self.current_milestone.human_feedback = feedback
            # Reset agent sign-offs since we need changes
            for agent in self.agents.values():
                agent.revoke_signoff(f"Milestone rejected: {feedback}")
            self.pending_verification = None
    
    def request_clarification(self, question_task: Task) -> None:
        """Set a pending clarification request for human"""
        self.pending_clarification = question_task
        self.state = ProjectState.AWAITING_INPUT
    
    def provide_clarification(self, answer: str) -> Task:
        """Human provides clarification, create response task"""
        if not self.pending_clarification:
            raise ValueError("No pending clarification request")
        
        from .task import TaskType
        
        response = self.pending_clarification.create_response(
            sender="human",
            response_type=None,  # Human response
            content=answer,
        )
        response.task_type = TaskType.CLARIFICATION_RESPONSE
        
        self.pending_clarification = None
        # Return to previous state (we'd need to track this, simplified for now)
        if self.state == ProjectState.AWAITING_INPUT:
            self.state = ProjectState.DISCOVERY
        
        return response
    
    def get_status_summary(self) -> str:
        """Get a human-readable status summary"""
        working = [r.value for r, a in self.agents.items() if a.status.value == "working"]
        waiting = [r.value for r, a in self.agents.items() if a.status.value == "waiting"]
        idle = [r.value for r, a in self.agents.items() if a.status.value == "idle"]
        
        lines = [
            f"{self.state.emoji} Project: {self.name}",
            f"State: {self.state.value}",
            f"Working: {len(working)} | Waiting: {len(waiting)} | Idle: {len(idle)}",
        ]
        
        # Add blockers
        for role, agent in self.agents.items():
            if agent.waiting_reason:
                lines.append(f"  ⏳ {role.value}: {agent.waiting_reason}")
        
        return "\n".join(lines)
