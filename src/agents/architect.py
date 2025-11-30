from __future__ import annotations
"""Software Architect Agent - designs the technical architecture"""

from typing import Optional

from ..core.models import (
    AgentRole, Task, TaskType, Priority, ResponseType,
    Artifact, ArtifactType, Project,
)
from ..core.ports.llm import LLMPort
from ..runtime.queue import MessageBus
from .base import BaseAgent, TaskResult
from .prompts import ARCHITECT_SYSTEM_PROMPT


class ArchitectAgent(BaseAgent):
    """
    Software Architect agent - owns technical design and architecture.
    
    Responsibilities:
    - Create technical design from requirements
    - Make technology decisions
    - Define APIs and data models
    - Review implementation alignment
    - Work with Developer on technical details
    """
    
    def __init__(
        self,
        role: AgentRole,
        llm: LLMPort,
        project: Project,
        message_bus: MessageBus,
    ):
        super().__init__(role, llm, project, message_bus)
        self._design_ready = False
    
    def get_system_prompt(self) -> str:
        return ARCHITECT_SYSTEM_PROMPT
    
    async def process_task(self, task: Task) -> TaskResult:
        """Process incoming tasks"""
        
        if task.task_type == TaskType.REQUEST:
            if "requirements" in task.subject.lower() or "design" in task.subject.lower():
                return await self._handle_design_request(task)
            elif "review" in task.subject.lower():
                return await self._handle_review_request(task)
            else:
                return await self._handle_agent_request(task)
        
        elif task.task_type == TaskType.FEEDBACK:
            return await self._handle_feedback(task)
        
        elif task.task_type == TaskType.QUESTION:
            return await self._handle_question(task)
        
        elif task.task_type == TaskType.RESPONSE:
            return await self._handle_response(task)
        
        else:
            return TaskResult(success=True)
    
    async def _handle_design_request(self, task: Task) -> TaskResult:
        """Create technical design from requirements"""
        requirements = task.content
        
        # Store in memory
        self.memory.project_context = f"Designing system for:\n{requirements}"
        
        # Create design
        design_prompt = f"""
Create a technical design for this system based on the requirements:

REQUIREMENTS:
{requirements}

Create a design document with:

1. **System Overview**
   - What we're building (1-2 sentences)
   - Key components

2. **Architecture**
   - Module/file structure
   - Key classes/functions
   - Data flow

3. **Data Model**
   - Key data structures (as Python dataclasses or similar)
   - Database schema (if using a database)

4. **Implementation Plan**
   - Ordered list of files to create
   - What each file should contain

5. **Technology Choices**
   - Language: Python
   - Key libraries to use
   - Rationale for choices

Keep it simple and practical. This should be directly implementable by a Developer.
Focus on clean, maintainable code structure.
"""
        
        design_content = await self.think(design_prompt)
        
        # Create design artifact
        design_artifact = Artifact(
            name="design.md",
            artifact_type=ArtifactType.DESIGN,
            content=design_content,
            file_path="docs/design.md",
            language="markdown",
            created_by=self.role,
            owner=self.role,
            description="Technical architecture and design",
        )
        
        result = TaskResult(
            success=True,
            artifacts_created=[design_artifact],
            decision_made=(
                "System design",
                "Created modular architecture",
                "Keeping design simple and focused on requirements",
            ),
        )
        
        # Hand off to Developer
        handoff_task = self.create_task(
            recipient=AgentRole.DEVELOPER,
            task_type=TaskType.REQUEST,
            subject="Design Ready for Implementation",
            content=f"""
The Architect has completed the technical design. Please implement it.

DESIGN:
{design_content}

Please:
1. Implement the code according to this design
2. Write unit tests for key functionality
3. If you have questions or concerns about the design, ask me
4. When implementation is ready, hand off to Tester

Follow Python best practices. Keep it clean and simple.
""",
            priority=Priority.HIGH,
            payload={"design_artifact_id": str(design_artifact.id)},
        )
        
        result.outgoing_tasks.append(handoff_task)
        self._design_ready = True
        
        return result
    
    async def _handle_review_request(self, task: Task) -> TaskResult:
        """Review implementation alignment with design"""
        code_to_review = task.content
        
        # Get current design
        design = self._get_design_artifact()
        design_content = design.content if design else "No design document found"
        
        review_prompt = f"""
Review this implementation for alignment with the design:

DESIGN:
{design_content}

IMPLEMENTATION TO REVIEW:
{code_to_review}

Evaluate:
1. Does it follow the designed architecture?
2. Are the patterns correct?
3. Any deviations that need addressing?
4. Any improvements suggested?

Provide specific, actionable feedback.
If it looks good, say "APPROVED" and explain why.
If changes needed, list them clearly.
"""
        
        review_content = await self.think(review_prompt)
        
        approved = "APPROVED" in review_content.upper()
        
        response = task.create_response(
            sender=self.role,
            response_type=ResponseType.ACCEPT if approved else ResponseType.COUNTER,
            content=review_content,
            payload={"approved": approved},
        )
        
        if approved:
            self.memory.add_decision(
                "Implementation review",
                "Approved",
                "Code follows design patterns correctly",
            )
        
        return TaskResult(success=True, response_task=response)
    
    async def _handle_agent_request(self, task: Task) -> TaskResult:
        """Handle general requests from other agents"""
        evaluation = await self.evaluate_request(task)
        
        if evaluation == ResponseType.ACCEPT:
            response_content = await self.think(
                f"Respond to this request from {task.sender}: {task.content}",
            )
            
            response = task.create_response(
                sender=self.role,
                response_type=ResponseType.ACCEPT,
                content=response_content,
            )
            
            return TaskResult(success=True, response_task=response)
        
        else:
            # Counter or reject with explanation
            explanation = await self.think(
                f"Explain why I'm responding with {evaluation.value} to: {task.content}",
            )
            
            response = task.create_response(
                sender=self.role,
                response_type=evaluation,
                content=explanation,
            )
            
            return TaskResult(success=True, response_task=response)
    
    async def _handle_feedback(self, task: Task) -> TaskResult:
        """Handle feedback from Developer or Tester"""
        self.memory.add_learning(f"Feedback from {task.sender}: {task.content}")
        
        # Check if design update needed
        if "design" in task.content.lower() or "issue" in task.content.lower():
            design = self._get_design_artifact()
            if design:
                update_prompt = f"""
Consider this feedback and decide if design needs updating:

Current Design:
{design.content}

Feedback from {task.sender}:
{task.content}

If design needs updating, provide the updated section.
If no update needed, explain why and say "NO_UPDATE_NEEDED".
"""
                
                response = await self.think(update_prompt)
                
                if "NO_UPDATE_NEEDED" not in response.upper():
                    # Design needs update
                    design.update_content(
                        design.content + f"\n\n## Update based on feedback\n{response}",
                        self.role,
                    )
                    
                    # Notify Developer of design change
                    notify_task = self.create_task(
                        recipient=AgentRole.DEVELOPER,
                        task_type=TaskType.NOTIFICATION,
                        subject="Design Updated",
                        content=f"The design has been updated based on feedback:\n\n{response}",
                        requires_response=False,
                    )
                    
                    return TaskResult(
                        success=True,
                        artifacts_updated=[design],
                        outgoing_tasks=[notify_task],
                    )
        
        return TaskResult(success=True)
    
    async def _handle_question(self, task: Task) -> TaskResult:
        """Handle questions from other agents"""
        design = self._get_design_artifact()
        context = design.content if design else ""
        
        answer = await self.think(
            f"Answer this technical question from {task.sender}: {task.content}",
            context=context,
        )
        
        response = task.create_response(
            sender=self.role,
            response_type=ResponseType.ACCEPT,
            content=answer,
        )
        
        return TaskResult(success=True, response_task=response)
    
    async def _handle_response(self, task: Task) -> TaskResult:
        """Handle responses to our requests"""
        self.memory.add_learning(f"Response from {task.sender}: {task.content[:100]}...")
        return TaskResult(success=True)
    
    def _get_design_artifact(self) -> Optional[Artifact]:
        """Get the current design artifact"""
        designs = self.project.get_artifacts_by_type(ArtifactType.DESIGN)
        return designs[0] if designs else None
