from __future__ import annotations
"""Storage Port - interface for persistence"""

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from ..models import Project, AgentState, Artifact, Task


class StoragePort(ABC):
    """
    Port for data persistence.
    Implementations can use SQLite, PostgreSQL, Redis, file system, etc.
    """
    
    # Project operations
    
    @abstractmethod
    async def save_project(self, project: Project) -> None:
        """Save or update a project"""
        pass
    
    @abstractmethod
    async def load_project(self, project_id: UUID) -> Optional[Project]:
        """Load a project by ID"""
        pass
    
    @abstractmethod
    async def list_projects(self) -> list[Project]:
        """List all projects"""
        pass
    
    @abstractmethod
    async def delete_project(self, project_id: UUID) -> None:
        """Delete a project"""
        pass
    
    # Agent state operations
    
    @abstractmethod
    async def save_agent_state(self, project_id: UUID, agent_state: AgentState) -> None:
        """Save agent state for a project"""
        pass
    
    @abstractmethod
    async def load_agent_state(self, project_id: UUID, agent_id: UUID) -> Optional[AgentState]:
        """Load agent state"""
        pass
    
    # Artifact operations
    
    @abstractmethod
    async def save_artifact(self, project_id: UUID, artifact: Artifact) -> None:
        """Save an artifact"""
        pass
    
    @abstractmethod
    async def load_artifact(self, artifact_id: UUID) -> Optional[Artifact]:
        """Load an artifact by ID"""
        pass
    
    @abstractmethod
    async def list_artifacts(self, project_id: UUID) -> list[Artifact]:
        """List all artifacts for a project"""
        pass
    
    # Task/Activity log operations
    
    @abstractmethod
    async def append_task(self, project_id: UUID, task: Task) -> None:
        """Append a task to the activity log"""
        pass
    
    @abstractmethod
    async def get_recent_tasks(self, project_id: UUID, limit: int = 50) -> list[Task]:
        """Get recent tasks from activity log"""
        pass
    
    # File output operations
    
    @abstractmethod
    async def write_output_file(self, project_id: UUID, file_path: str, content: str) -> str:
        """
        Write a file to the project output directory.
        Returns the full path to the written file.
        """
        pass
    
    @abstractmethod
    async def read_output_file(self, project_id: UUID, file_path: str) -> Optional[str]:
        """Read a file from the project output directory"""
        pass
    
    @abstractmethod
    async def list_output_files(self, project_id: UUID) -> list[str]:
        """List all files in the project output directory"""
        pass
