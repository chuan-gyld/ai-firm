from __future__ import annotations
"""Developer Agent - implements code based on design"""

from typing import Optional

from ..core.models import (
    AgentRole, Task, TaskType, Priority, ResponseType,
    Artifact, ArtifactType, Project,
)
from ..core.ports.llm import LLMPort
from ..runtime.queue import MessageBus
from .base import BaseAgent, TaskResult
from .prompts import DEVELOPER_SYSTEM_PROMPT


class DeveloperAgent(BaseAgent):
    """
    Developer agent - implements the code.
    
    Responsibilities:
    - Implement code based on Architect's design
    - Write unit tests
    - Fix bugs reported by Tester
    - Ask Architect for clarification on technical details
    """
    
    def __init__(
        self,
        role: AgentRole,
        llm: LLMPort,
        project: Project,
        message_bus: MessageBus,
    ):
        super().__init__(role, llm, project, message_bus)
        self._implementation_complete = False
        self._files_created: list[str] = []
    
    def get_system_prompt(self) -> str:
        return DEVELOPER_SYSTEM_PROMPT
    
    async def process_task(self, task: Task) -> TaskResult:
        """Process incoming tasks"""
        
        if task.task_type == TaskType.REQUEST:
            if "design" in task.subject.lower() or "implement" in task.subject.lower():
                return await self._handle_implementation_request(task)
            elif "fix" in task.subject.lower() or "bug" in task.subject.lower():
                return await self._handle_bug_fix_request(task)
            else:
                return await self._handle_agent_request(task)
        
        elif task.task_type == TaskType.FEEDBACK:
            return await self._handle_feedback(task)
        
        elif task.task_type == TaskType.NOTIFICATION:
            return await self._handle_notification(task)
        
        elif task.task_type == TaskType.RESPONSE:
            return await self._handle_response(task)
        
        else:
            return TaskResult(success=True)
    
    async def _handle_implementation_request(self, task: Task) -> TaskResult:
        """Implement code based on design"""
        design = task.content
        
        # Store in memory
        self.memory.project_context = f"Implementing design:\n{design[:500]}..."
        
        # First, understand what files to create
        plan_prompt = f"""
Based on this design, list the files that need to be created:

DESIGN:
{design}

List each file with:
1. File path (e.g., todo.py, db.py)
2. Brief description of what it contains

Format as:
FILE: path/to/file.py
DESCRIPTION: What this file contains
---
"""
        
        plan = await self.think(plan_prompt)
        
        # Parse the plan and create files
        files_to_create = self._parse_file_plan(plan)
        
        artifacts_created = []
        all_code = []
        
        for file_path, description in files_to_create:
            code_content = await self._generate_code_file(file_path, description, design)
            
            artifact = Artifact(
                name=file_path,
                artifact_type=ArtifactType.CODE,
                content=code_content,
                file_path=file_path,
                language="python" if file_path.endswith(".py") else None,
                created_by=self.role,
                owner=self.role,
                description=description,
            )
            
            artifacts_created.append(artifact)
            all_code.append(f"# {file_path}\n{code_content}")
            self._files_created.append(file_path)
        
        result = TaskResult(
            success=True,
            artifacts_created=artifacts_created,
            decision_made=(
                "Implementation",
                f"Created {len(artifacts_created)} files",
                "Following design specification",
            ),
        )
        
        # Hand off to Tester
        newline = "\n"
        code_listing = newline.join(all_code)
        files_listing = ", ".join(self._files_created)
        handoff_task = self.create_task(
            recipient=AgentRole.TESTER,
            task_type=TaskType.REQUEST,
            subject="Implementation Ready for Testing",
            content=f"""
The Developer has completed the initial implementation. Please test it.

FILES CREATED:
{files_listing}

CODE:
{code_listing}

Please:
1. Review the code
2. Create test cases based on requirements
3. Run tests and report any bugs
4. Sign off when quality is acceptable
""",
            priority=Priority.HIGH,
        )
        
        result.outgoing_tasks.append(handoff_task)
        self._implementation_complete = True
        
        return result
    
    def _parse_file_plan(self, plan: str) -> list[tuple[str, str]]:
        """Parse file plan into list of (path, description)"""
        files = []
        current_file = None
        current_desc = None
        
        for line in plan.split("\n"):
            line = line.strip()
            if line.startswith("FILE:"):
                if current_file:
                    files.append((current_file, current_desc or ""))
                current_file = line.replace("FILE:", "").strip()
                current_desc = None
            elif line.startswith("DESCRIPTION:"):
                current_desc = line.replace("DESCRIPTION:", "").strip()
            elif line == "---":
                if current_file:
                    files.append((current_file, current_desc or ""))
                current_file = None
                current_desc = None
        
        if current_file:
            files.append((current_file, current_desc or ""))
        
        # Default files if none parsed
        if not files:
            files = [
                ("main.py", "Main entry point"),
                ("core.py", "Core functionality"),
            ]
        
        return files
    
    async def _generate_code_file(
        self,
        file_path: str,
        description: str,
        design: str,
    ) -> str:
        """Generate code for a specific file"""
        code_prompt = f"""
Generate the Python code for this file:

FILE: {file_path}
PURPOSE: {description}

DESIGN CONTEXT:
{design}

Requirements:
1. Write clean, working Python code
2. Include type hints
3. Include docstrings
4. Handle errors gracefully
5. Follow PEP 8 style

Output ONLY the Python code, no markdown or explanations.
Start directly with the imports or code.
"""
        
        code = await self.think(code_prompt)
        
        # Clean up any markdown artifacts
        code = code.strip()
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        
        return code.strip()
    
    async def _handle_bug_fix_request(self, task: Task) -> TaskResult:
        """Fix a bug reported by Tester"""
        bug_report = task.content
        
        self.memory.add_learning(f"Bug to fix: {bug_report[:100]}...")
        
        # Find relevant code artifacts
        code_artifacts = self.project.get_artifacts_by_type(ArtifactType.CODE)
        
        if not code_artifacts:
            return TaskResult(
                success=False,
                concern_raised=("No code to fix", "high"),
            )
        
        # Generate fix
        newline = "\n"
        current_code = newline.join([f"# {a.file_path}{newline}{a.content}" for a in code_artifacts])
        fix_prompt = f"""
Fix this bug in the code:

BUG REPORT:
{bug_report}

CURRENT CODE:
{current_code}

Provide the fixed code for each affected file.
Format as:
FILE: path/to/file.py
```python
<fixed code>
```
---
"""
        
        fix_response = await self.think(fix_prompt)
        
        # Parse and apply fixes
        updated_artifacts = await self._apply_fixes(fix_response, code_artifacts)
        
        result = TaskResult(
            success=True,
            artifacts_updated=updated_artifacts,
            decision_made=(
                "Bug fix",
                f"Fixed bug: {bug_report[:50]}...",
                "Applied fix based on bug report",
            ),
        )
        
        # Notify Tester fix is ready
        newline = "\n"
        updated_code = newline.join([f"# {a.file_path}{newline}{a.content}" for a in updated_artifacts])
        fixed_files = ", ".join([a.file_path for a in updated_artifacts])
        notify_task = self.create_task(
            recipient=AgentRole.TESTER,
            task_type=TaskType.NOTIFICATION,
            subject="Bug Fix Ready for Re-test",
            content=f"""
I've fixed the reported bug. Please re-test.

Original bug: {bug_report[:200]}...

Fixed files: {fixed_files}

UPDATED CODE:
{updated_code}
""",
            requires_response=False,
        )
        
        result.outgoing_tasks.append(notify_task)
        
        return result
    
    async def _apply_fixes(
        self,
        fix_response: str,
        existing_artifacts: list[Artifact],
    ) -> list[Artifact]:
        """Apply code fixes to artifacts"""
        updated = []
        
        current_file = None
        current_code = []
        in_code_block = False
        
        for line in fix_response.split("\n"):
            if line.strip().startswith("FILE:"):
                # Save previous file if exists
                if current_file and current_code:
                    for artifact in existing_artifacts:
                        if artifact.file_path == current_file:
                            artifact.update_content("\n".join(current_code), self.role)
                            updated.append(artifact)
                            break
                
                current_file = line.replace("FILE:", "").strip()
                current_code = []
                in_code_block = False
            elif line.strip().startswith("```python"):
                in_code_block = True
            elif line.strip() == "```":
                in_code_block = False
            elif in_code_block:
                current_code.append(line)
        
        # Don't forget last file
        if current_file and current_code:
            for artifact in existing_artifacts:
                if artifact.file_path == current_file:
                    artifact.update_content("\n".join(current_code), self.role)
                    updated.append(artifact)
                    break
        
        return updated
    
    async def _handle_agent_request(self, task: Task) -> TaskResult:
        """Handle general requests"""
        response_content = await self.think(
            f"Respond to request from {task.sender}: {task.content}",
        )
        
        response = task.create_response(
            sender=self.role,
            response_type=ResponseType.ACCEPT,
            content=response_content,
        )
        
        return TaskResult(success=True, response_task=response)
    
    async def _handle_feedback(self, task: Task) -> TaskResult:
        """Handle feedback from other agents"""
        self.memory.add_learning(f"Feedback from {task.sender}: {task.content}")
        
        # Check if it's a design issue that needs escalation
        if "design" in task.content.lower() and task.sender == AgentRole.TESTER:
            # Escalate to Architect
            escalate_task = self.create_task(
                recipient=AgentRole.ARCHITECT,
                task_type=TaskType.FEEDBACK,
                subject="Potential Design Issue from Testing",
                content=f"""
The Tester has flagged an issue that might be a design problem:

{task.content}

Please review and advise if design changes are needed.
""",
                priority=Priority.HIGH,
            )
            
            return TaskResult(success=True, outgoing_tasks=[escalate_task])
        
        return TaskResult(success=True)
    
    async def _handle_notification(self, task: Task) -> TaskResult:
        """Handle notifications"""
        self.memory.add_learning(f"Notification from {task.sender}: {task.content[:100]}...")
        
        # If design update, may need to update code
        if "design" in task.subject.lower() and task.sender == AgentRole.ARCHITECT:
            # Note the update for consideration
            self.memory.add_concern("Design updated - may need code changes", "medium")
        
        return TaskResult(success=True)
    
    async def _handle_response(self, task: Task) -> TaskResult:
        """Handle responses to our requests"""
        self.memory.add_learning(f"Response from {task.sender}: {task.content[:100]}...")
        return TaskResult(success=True)
