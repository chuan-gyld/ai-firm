from __future__ import annotations
"""SQLite storage adapter - simple file-based persistence"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

import aiosqlite

from ..core.models import Project, AgentState, Artifact, Task, AgentRole
from ..core.ports.storage import StoragePort


def _serialize_datetime(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, UUID):
        return str(obj)
    elif hasattr(obj, 'value'):  # Enum
        return obj.value
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _deserialize_datetime(dct):
    """JSON deserializer for datetime strings"""
    for key, value in dct.items():
        if isinstance(value, str):
            try:
                dct[key] = datetime.fromisoformat(value)
            except (ValueError, TypeError):
                pass
    return dct


class SQLiteStorageAdapter(StoragePort):
    """
    SQLite-based storage adapter.
    Stores data in a local SQLite database with JSON serialization for complex objects.
    """
    
    def __init__(self, db_path: str = "./state.db", output_dir: str = "./output"):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self._initialized = False
    
    async def _ensure_initialized(self) -> None:
        """Initialize database tables if needed"""
        if self._initialized:
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    data JSON,
                    created_at TEXT,
                    updated_at TEXT
                );
                
                CREATE TABLE IF NOT EXISTS agent_states (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    role TEXT,
                    data JSON,
                    updated_at TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );
                
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    artifact_type TEXT,
                    name TEXT,
                    data JSON,
                    created_at TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );
                
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    task_type TEXT,
                    data JSON,
                    created_at TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_agent_project ON agent_states(project_id);
                CREATE INDEX IF NOT EXISTS idx_artifact_project ON artifacts(project_id);
                CREATE INDEX IF NOT EXISTS idx_task_project ON tasks(project_id);
            """)
            await db.commit()
        
        self._initialized = True
    
    def _project_to_dict(self, project: Project) -> dict:
        """Convert project to JSON-serializable dict"""
        return {
            "id": str(project.id),
            "name": project.name,
            "original_idea": project.original_idea,
            "refined_description": project.refined_description,
            "state": project.state.value,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
            "completed_at": project.completed_at.isoformat() if project.completed_at else None,
            "output_directory": project.output_directory,
            # Agents stored separately
            # Artifacts stored separately
            # Tasks stored separately
        }
    
    def _dict_to_project(self, data: dict) -> Project:
        """Convert dict back to Project"""
        from ..core.models.project import ProjectState
        
        project = Project(
            id=UUID(data["id"]),
            name=data["name"],
            original_idea=data["original_idea"],
            refined_description=data.get("refined_description", ""),
            state=ProjectState(data["state"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            output_directory=data.get("output_directory", ""),
        )
        return project
    
    async def save_project(self, project: Project) -> None:
        """Save or update a project"""
        await self._ensure_initialized()
        
        data = self._project_to_dict(project)
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO projects (id, name, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(project.id),
                    project.name,
                    json.dumps(data, default=_serialize_datetime),
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                )
            )
            await db.commit()
        
        # Save agent states
        for role, agent_state in project.agents.items():
            await self.save_agent_state(project.id, agent_state)
        
        # Save artifacts
        for artifact_id, artifact in project.artifacts.items():
            await self.save_artifact(project.id, artifact)
    
    async def load_project(self, project_id: UUID) -> Optional[Project]:
        """Load a project by ID"""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT data FROM projects WHERE id = ?",
                (str(project_id),)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                
                data = json.loads(row["data"])
                project = self._dict_to_project(data)
        
        # Load agent states
        project.initialize_agents()
        for role in AgentRole:
            agent_states = await self._load_agent_states_by_project(project_id)
            for state in agent_states:
                project.agents[state.role] = state
        
        # Load artifacts
        artifacts = await self.list_artifacts(project_id)
        for artifact in artifacts:
            project.artifacts[artifact.id] = artifact
        
        return project
    
    async def _load_agent_states_by_project(self, project_id: UUID) -> list[AgentState]:
        """Load all agent states for a project"""
        await self._ensure_initialized()
        
        states = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT data FROM agent_states WHERE project_id = ?",
                (str(project_id),)
            ) as cursor:
                async for row in cursor:
                    data = json.loads(row["data"])
                    state = self._dict_to_agent_state(data)
                    states.append(state)
        
        return states
    
    def _agent_state_to_dict(self, state: AgentState) -> dict:
        """Convert AgentState to dict"""
        from ..core.models.agent import AgentStatus
        
        return {
            "id": str(state.id),
            "role": state.role.value,
            "status": state.status.value,
            "current_task_id": str(state.current_task_id) if state.current_task_id else None,
            "current_task_summary": state.current_task_summary,
            "waiting_reason": state.waiting_reason,
            "inbox_count": state.inbox_count,
            "outbox_count": state.outbox_count,
            "last_activity": state.last_activity.isoformat(),
            "tasks_completed": state.tasks_completed,
            "signed_off": state.signed_off,
            "signoff_blockers": state.signoff_blockers,
            "memory": {
                "project_context": state.memory.project_context,
                "decision_history": [
                    {
                        "id": str(d.id),
                        "subject": d.subject,
                        "choice": d.choice,
                        "rationale": d.rationale,
                        "made_at": d.made_at.isoformat(),
                    }
                    for d in state.memory.decision_history
                ],
                "active_concerns": [
                    {
                        "id": str(c.id),
                        "description": c.description,
                        "severity": c.severity,
                        "raised_at": c.raised_at.isoformat(),
                        "resolved": c.resolved,
                    }
                    for c in state.memory.active_concerns
                ],
                "relationship_notes": state.memory.relationship_notes,
                "learnings": state.memory.learnings,
            },
        }
    
    def _dict_to_agent_state(self, data: dict) -> AgentState:
        """Convert dict to AgentState"""
        from ..core.models.agent import AgentStatus, AgentMemory, Decision, Concern
        
        memory_data = data.get("memory", {})
        memory = AgentMemory(
            project_context=memory_data.get("project_context", ""),
            decision_history=[
                Decision(
                    id=UUID(d["id"]),
                    subject=d["subject"],
                    choice=d["choice"],
                    rationale=d["rationale"],
                    made_at=datetime.fromisoformat(d["made_at"]),
                )
                for d in memory_data.get("decision_history", [])
            ],
            active_concerns=[
                Concern(
                    id=UUID(c["id"]),
                    description=c["description"],
                    severity=c["severity"],
                    raised_at=datetime.fromisoformat(c["raised_at"]),
                    resolved=c["resolved"],
                )
                for c in memory_data.get("active_concerns", [])
            ],
            relationship_notes=memory_data.get("relationship_notes", {}),
            learnings=memory_data.get("learnings", []),
        )
        
        return AgentState(
            id=UUID(data["id"]),
            role=AgentRole(data["role"]),
            status=AgentStatus(data["status"]),
            memory=memory,
            current_task_id=UUID(data["current_task_id"]) if data.get("current_task_id") else None,
            current_task_summary=data.get("current_task_summary", ""),
            waiting_reason=data.get("waiting_reason"),
            inbox_count=data.get("inbox_count", 0),
            outbox_count=data.get("outbox_count", 0),
            last_activity=datetime.fromisoformat(data["last_activity"]),
            tasks_completed=data.get("tasks_completed", 0),
            signed_off=data.get("signed_off", False),
            signoff_blockers=data.get("signoff_blockers", []),
        )
    
    async def list_projects(self) -> list[Project]:
        """List all projects"""
        await self._ensure_initialized()
        
        projects = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT id FROM projects ORDER BY updated_at DESC") as cursor:
                async for row in cursor:
                    project = await self.load_project(UUID(row["id"]))
                    if project:
                        projects.append(project)
        
        return projects
    
    async def delete_project(self, project_id: UUID) -> None:
        """Delete a project and all associated data"""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM tasks WHERE project_id = ?", (str(project_id),))
            await db.execute("DELETE FROM artifacts WHERE project_id = ?", (str(project_id),))
            await db.execute("DELETE FROM agent_states WHERE project_id = ?", (str(project_id),))
            await db.execute("DELETE FROM projects WHERE id = ?", (str(project_id),))
            await db.commit()
    
    async def save_agent_state(self, project_id: UUID, agent_state: AgentState) -> None:
        """Save agent state"""
        await self._ensure_initialized()
        
        data = self._agent_state_to_dict(agent_state)
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO agent_states (id, project_id, role, data, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(agent_state.id),
                    str(project_id),
                    agent_state.role.value,
                    json.dumps(data, default=_serialize_datetime),
                    datetime.utcnow().isoformat(),
                )
            )
            await db.commit()
    
    async def load_agent_state(self, project_id: UUID, agent_id: UUID) -> Optional[AgentState]:
        """Load agent state"""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT data FROM agent_states WHERE id = ? AND project_id = ?",
                (str(agent_id), str(project_id))
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                
                data = json.loads(row["data"])
                return self._dict_to_agent_state(data)
    
    async def save_artifact(self, project_id: UUID, artifact: Artifact) -> None:
        """Save an artifact"""
        await self._ensure_initialized()
        
        data = {
            "id": str(artifact.id),
            "name": artifact.name,
            "artifact_type": artifact.artifact_type.value,
            "content": artifact.content,
            "file_path": artifact.file_path,
            "language": artifact.language,
            "created_by": artifact.created_by.value,
            "owner": artifact.owner.value,
            "version": artifact.version,
            "created_at": artifact.created_at.isoformat(),
            "updated_at": artifact.updated_at.isoformat(),
            "description": artifact.description,
            "tags": artifact.tags,
            "is_draft": artifact.is_draft,
            "is_approved": artifact.is_approved,
            "approved_by": artifact.approved_by.value if artifact.approved_by else None,
        }
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO artifacts (id, project_id, artifact_type, name, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(artifact.id),
                    str(project_id),
                    artifact.artifact_type.value,
                    artifact.name,
                    json.dumps(data, default=_serialize_datetime),
                    artifact.created_at.isoformat(),
                )
            )
            await db.commit()
    
    async def load_artifact(self, artifact_id: UUID) -> Optional[Artifact]:
        """Load an artifact by ID"""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT data FROM artifacts WHERE id = ?",
                (str(artifact_id),)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                
                data = json.loads(row["data"])
                return self._dict_to_artifact(data)
    
    def _dict_to_artifact(self, data: dict) -> Artifact:
        """Convert dict to Artifact"""
        from ..core.models.artifact import ArtifactType
        
        return Artifact(
            id=UUID(data["id"]),
            name=data["name"],
            artifact_type=ArtifactType(data["artifact_type"]),
            content=data["content"],
            file_path=data.get("file_path"),
            language=data.get("language"),
            created_by=AgentRole(data["created_by"]),
            owner=AgentRole(data["owner"]),
            version=data["version"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            is_draft=data.get("is_draft", True),
            is_approved=data.get("is_approved", False),
            approved_by=AgentRole(data["approved_by"]) if data.get("approved_by") else None,
        )
    
    async def list_artifacts(self, project_id: UUID) -> list[Artifact]:
        """List all artifacts for a project"""
        await self._ensure_initialized()
        
        artifacts = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT data FROM artifacts WHERE project_id = ?",
                (str(project_id),)
            ) as cursor:
                async for row in cursor:
                    data = json.loads(row["data"])
                    artifact = self._dict_to_artifact(data)
                    artifacts.append(artifact)
        
        return artifacts
    
    async def append_task(self, project_id: UUID, task: Task) -> None:
        """Append a task to the activity log"""
        await self._ensure_initialized()
        
        sender = task.sender if isinstance(task.sender, str) else task.sender.value
        recipient = task.recipient if isinstance(task.recipient, str) else task.recipient.value
        
        data = {
            "id": str(task.id),
            "sender": sender,
            "recipient": recipient,
            "task_type": task.task_type.value,
            "priority": task.priority.value,
            "subject": task.subject,
            "content": task.content,
            "payload": task.payload,
            "thread_id": str(task.thread_id) if task.thread_id else None,
            "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
            "created_at": task.created_at.isoformat(),
            "status": task.status.value,
        }
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO tasks (id, project_id, task_type, data, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(task.id),
                    str(project_id),
                    task.task_type.value,
                    json.dumps(data, default=_serialize_datetime),
                    task.created_at.isoformat(),
                )
            )
            await db.commit()
    
    async def get_recent_tasks(self, project_id: UUID, limit: int = 50) -> list[Task]:
        """Get recent tasks from activity log"""
        await self._ensure_initialized()
        
        tasks = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT data FROM tasks WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                (str(project_id), limit)
            ) as cursor:
                async for row in cursor:
                    data = json.loads(row["data"])
                    task = self._dict_to_task(data)
                    tasks.append(task)
        
        return list(reversed(tasks))  # Return in chronological order
    
    def _dict_to_task(self, data: dict) -> Task:
        """Convert dict to Task"""
        from ..core.models.task import TaskType, TaskStatus, Priority
        
        sender = data["sender"]
        recipient = data["recipient"]
        
        # Try to convert to AgentRole if possible
        try:
            sender = AgentRole(sender)
        except ValueError:
            pass
        try:
            recipient = AgentRole(recipient)
        except ValueError:
            pass
        
        return Task(
            id=UUID(data["id"]),
            sender=sender,
            recipient=recipient,
            task_type=TaskType(data["task_type"]),
            priority=Priority(data["priority"]),
            subject=data["subject"],
            content=data["content"],
            payload=data.get("payload", {}),
            thread_id=UUID(data["thread_id"]) if data.get("thread_id") else None,
            parent_task_id=UUID(data["parent_task_id"]) if data.get("parent_task_id") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            status=TaskStatus(data["status"]),
        )
    
    async def write_output_file(self, project_id: UUID, file_path: str, content: str) -> str:
        """Write a file to the project output directory"""
        project_dir = self.output_dir / str(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        
        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        full_path.write_text(content)
        return str(full_path)
    
    async def read_output_file(self, project_id: UUID, file_path: str) -> Optional[str]:
        """Read a file from the project output directory"""
        full_path = self.output_dir / str(project_id) / file_path
        
        if not full_path.exists():
            return None
        
        return full_path.read_text()
    
    async def list_output_files(self, project_id: UUID) -> list[str]:
        """List all files in the project output directory"""
        project_dir = self.output_dir / str(project_id)
        
        if not project_dir.exists():
            return []
        
        files = []
        for path in project_dir.rglob("*"):
            if path.is_file():
                files.append(str(path.relative_to(project_dir)))
        
        return sorted(files)
