from __future__ import annotations
"""Task and Message domain models - work items that flow between agents"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, Enum
from typing import NewType, Optional, Any
from uuid import UUID, uuid4

from .agent import AgentRole

TaskId = NewType("TaskId", UUID)


class Priority(IntEnum):
    """Task priority - lower number = higher priority"""
    CRITICAL = 0    # Human intervention, system alerts
    HIGH = 1        # Blockers, urgent requests
    MEDIUM = 2      # Normal work items
    LOW = 3         # Nice-to-haves, background tasks
    
    @property
    def label(self) -> str:
        labels = {
            Priority.CRITICAL: "🔴 CRITICAL",
            Priority.HIGH: "🟠 High",
            Priority.MEDIUM: "🟡 Medium",
            Priority.LOW: "🟢 Low",
        }
        return labels[self]


class TaskType(str, Enum):
    """Type of task/message"""
    # Work requests
    REQUEST = "request"              # Asking another agent to do something
    RESPONSE = "response"            # Answering a previous request
    
    # Information sharing
    NOTIFICATION = "notification"    # FYI, no response expected
    FEEDBACK = "feedback"            # Comments on work done
    
    # Review and approval
    REVIEW_REQUEST = "review_request"
    REVIEW_RESPONSE = "review_response"
    
    # Questions and clarifications
    QUESTION = "question"
    ANSWER = "answer"
    
    # Human interaction
    CLARIFICATION_REQUEST = "clarification_request"  # Agent needs human input
    CLARIFICATION_RESPONSE = "clarification_response"
    MILESTONE_VERIFICATION = "milestone_verification"
    
    # System
    SYSTEM = "system"                # System commands (pause, redirect)


class TaskStatus(str, Enum):
    """Status of a task in the queue"""
    PENDING = "pending"          # In queue, not started
    IN_PROGRESS = "in_progress"  # Currently being worked on
    BLOCKED = "blocked"          # Waiting on something
    COMPLETED = "completed"      # Done
    CANCELLED = "cancelled"      # Abandoned


class ResponseType(str, Enum):
    """How an agent can respond to a request"""
    ACCEPT = "accept"           # I'll do this as requested
    COUNTER = "counter"         # I propose a modification
    REJECT = "reject"           # I can't/won't do this
    CLARIFY = "clarify"         # I need more information
    ESCALATE = "escalate"       # Beyond my authority, escalating


@dataclass
class Task:
    """
    A unit of work or communication between agents.
    Tasks flow through prioritized inboxes.
    """
    id: TaskId = field(default_factory=lambda: TaskId(uuid4()))
    
    # Routing
    sender: AgentRole | str = ""     # Can be agent role or "human"
    recipient: AgentRole | str = ""  # Can be agent role or "broadcast"
    
    # Classification
    task_type: TaskType = TaskType.REQUEST
    priority: Priority = Priority.MEDIUM
    
    # Content
    subject: str = ""
    content: str = ""
    
    # Structured data payload (for code, artifacts, etc.)
    payload: dict[str, Any] = field(default_factory=dict)
    
    # Threading - for conversations
    thread_id: Optional[UUID] = None
    parent_task_id: Optional[TaskId] = None
    
    # References to other tasks or artifacts
    references: list[UUID] = field(default_factory=list)
    
    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    deadline: Optional[datetime] = None
    
    # Status
    status: TaskStatus = TaskStatus.PENDING
    
    # Response tracking
    requires_response: bool = True
    response_received: bool = False
    
    def __lt__(self, other: "Task") -> bool:
        """For priority queue ordering: compare by (priority, created_at)"""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at
    
    def create_response(
        self,
        sender: AgentRole,
        response_type: ResponseType,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> "Task":
        """Create a response task to this task"""
        return Task(
            sender=sender,
            recipient=self.sender,
            task_type=TaskType.RESPONSE,
            priority=self.priority,
            subject=f"Re: {self.subject}",
            content=content,
            payload={
                "response_type": response_type.value,
                **(payload or {}),
            },
            thread_id=self.thread_id or self.id,
            parent_task_id=self.id,
        )
    
    def mark_in_progress(self) -> None:
        """Mark task as being worked on"""
        self.status = TaskStatus.IN_PROGRESS
    
    def mark_completed(self) -> None:
        """Mark task as done"""
        self.status = TaskStatus.COMPLETED
    
    def mark_blocked(self) -> None:
        """Mark task as blocked"""
        self.status = TaskStatus.BLOCKED


@dataclass
class Message:
    """
    A simplified message for logging and display purposes.
    Created from Tasks for the activity feed.
    """
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    from_agent: str = ""
    to_agent: str = ""
    summary: str = ""
    task_type: TaskType = TaskType.NOTIFICATION
    
    @classmethod
    def from_task(cls, task: Task) -> "Message":
        """Create a message summary from a task"""
        sender = task.sender if isinstance(task.sender, str) else task.sender.value
        recipient = task.recipient if isinstance(task.recipient, str) else task.recipient.value
        
        return cls(
            id=task.id,
            timestamp=task.created_at,
            from_agent=sender,
            to_agent=recipient,
            summary=task.subject or task.content[:50],
            task_type=task.task_type,
        )
