from __future__ import annotations
"""Core domain models"""

from .agent import AgentId, AgentRole, AgentStatus, AgentState, AgentMemory
from .task import TaskId, TaskType, TaskStatus, Priority, Task, Message, ResponseType
from .artifact import ArtifactId, ArtifactType, Artifact, BugReport
from .project import ProjectId, ProjectState, Project

__all__ = [
    "AgentId",
    "AgentRole", 
    "AgentStatus",
    "AgentState",
    "AgentMemory",
    "TaskId",
    "TaskType",
    "TaskStatus",
    "Priority",
    "Task",
    "Message",
    "ResponseType",
    "ArtifactId",
    "BugReport",
    "ArtifactType",
    "Artifact",
    "ProjectId",
    "ProjectState",
    "Project",
]
