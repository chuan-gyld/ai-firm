from __future__ import annotations
"""Artifact domain models - documents, code, and other outputs created by agents"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import NewType, Optional
from uuid import UUID, uuid4

from .agent import AgentRole

ArtifactId = NewType("ArtifactId", UUID)


class ArtifactType(str, Enum):
    """Types of artifacts that agents create and maintain"""
    # PM artifacts
    REQUIREMENTS = "requirements"
    USER_STORY = "user_story"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    
    # Architect artifacts
    DESIGN = "design"
    API_SPEC = "api_spec"
    ARCHITECTURE_DECISION = "architecture_decision"
    
    # Developer artifacts
    CODE = "code"
    UNIT_TEST = "unit_test"
    IMPLEMENTATION_NOTES = "implementation_notes"
    
    # Tester artifacts
    TEST_PLAN = "test_plan"
    BUG_REPORT = "bug_report"
    TEST_RESULT = "test_result"
    
    # General
    DOCUMENT = "document"
    
    @property
    def owner_role(self) -> AgentRole:
        """Which role typically owns this artifact type"""
        ownership = {
            ArtifactType.REQUIREMENTS: AgentRole.PM,
            ArtifactType.USER_STORY: AgentRole.PM,
            ArtifactType.ACCEPTANCE_CRITERIA: AgentRole.PM,
            ArtifactType.DESIGN: AgentRole.ARCHITECT,
            ArtifactType.API_SPEC: AgentRole.ARCHITECT,
            ArtifactType.ARCHITECTURE_DECISION: AgentRole.ARCHITECT,
            ArtifactType.CODE: AgentRole.DEVELOPER,
            ArtifactType.UNIT_TEST: AgentRole.DEVELOPER,
            ArtifactType.IMPLEMENTATION_NOTES: AgentRole.DEVELOPER,
            ArtifactType.TEST_PLAN: AgentRole.TESTER,
            ArtifactType.BUG_REPORT: AgentRole.TESTER,
            ArtifactType.TEST_RESULT: AgentRole.TESTER,
            ArtifactType.DOCUMENT: AgentRole.PM,  # Default
        }
        return ownership.get(self, AgentRole.PM)


@dataclass
class Artifact:
    """
    A versioned artifact created by an agent.
    Artifacts are the tangible outputs of the AI company's work.
    """
    id: ArtifactId = field(default_factory=lambda: ArtifactId(uuid4()))
    
    # Identity
    name: str = ""
    artifact_type: ArtifactType = ArtifactType.DOCUMENT
    
    # Content
    content: str = ""
    
    # File info (for code artifacts)
    file_path: Optional[str] = None
    language: Optional[str] = None  # python, yaml, markdown, etc.
    
    # Ownership and versioning
    created_by: AgentRole = AgentRole.PM
    owner: AgentRole = AgentRole.PM
    version: int = 1
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)
    
    # Status
    is_draft: bool = True
    is_approved: bool = False
    approved_by: Optional[AgentRole] = None
    
    def update_content(self, new_content: str, updated_by: AgentRole) -> None:
        """Update the artifact content and increment version"""
        self.content = new_content
        self.version += 1
        self.updated_at = datetime.utcnow()
        # Reset approval status when content changes
        if updated_by != self.approved_by:
            self.is_approved = False
            self.approved_by = None
    
    def approve(self, approver: AgentRole) -> None:
        """Mark artifact as approved"""
        self.is_approved = True
        self.approved_by = approver
        self.is_draft = False
    
    def mark_final(self) -> None:
        """Mark artifact as final/complete"""
        self.is_draft = False


@dataclass 
class CodeFile(Artifact):
    """Specialized artifact for code files"""
    
    def __post_init__(self):
        self.artifact_type = ArtifactType.CODE
        self.owner = AgentRole.DEVELOPER
        
        # Infer language from file path if not set
        if self.file_path and not self.language:
            ext_to_lang = {
                ".py": "python",
                ".js": "javascript",
                ".ts": "typescript",
                ".yaml": "yaml",
                ".yml": "yaml",
                ".json": "json",
                ".md": "markdown",
                ".sql": "sql",
            }
            for ext, lang in ext_to_lang.items():
                if self.file_path.endswith(ext):
                    self.language = lang
                    break


@dataclass
class BugReport(Artifact):
    """Specialized artifact for bug reports"""
    severity: str = "medium"  # low, medium, high, critical
    status: str = "open"  # open, in_progress, resolved, wont_fix
    steps_to_reproduce: str = ""
    expected_behavior: str = ""
    actual_behavior: str = ""
    assigned_to: Optional[AgentRole] = None
    resolution: Optional[str] = None
    
    def __post_init__(self):
        self.artifact_type = ArtifactType.BUG_REPORT
        self.owner = AgentRole.TESTER
    
    def assign(self, agent: AgentRole) -> None:
        """Assign bug to an agent for fixing"""
        self.assigned_to = agent
        self.status = "in_progress"
    
    def resolve(self, resolution: str) -> None:
        """Mark bug as resolved"""
        self.status = "resolved"
        self.resolution = resolution
        self.updated_at = datetime.utcnow()
