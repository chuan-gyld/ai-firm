from __future__ import annotations
"""Product Manager Agent - refines ideas into requirements"""

from typing import Optional

from ..core.models import (
    AgentRole, Task, TaskType, Priority, ResponseType,
    Artifact, ArtifactType, Project,
)
from ..core.ports.llm import LLMPort, LLMMessage
from ..runtime.queue import MessageBus
from .base import BaseAgent, TaskResult
from .prompts import PM_SYSTEM_PROMPT


class ProductManagerAgent(BaseAgent):
    """
    Product Manager agent - owns requirements and user stories.
    
    Responsibilities:
    - Refine raw ideas into clear requirements
    - Create user stories with acceptance criteria
    - Ask for human clarification when needed
    - Hand off to Architect when requirements are ready
    """
    
    def __init__(
        self,
        role: AgentRole,
        llm: LLMPort,
        project: Project,
        message_bus: MessageBus,
    ):
        super().__init__(role, llm, project, message_bus)
        self._requirements_ready = False
    
    def get_system_prompt(self) -> str:
        return PM_SYSTEM_PROMPT
    
    async def process_task(self, task: Task) -> TaskResult:
        """Process incoming tasks"""
        
        if task.task_type == TaskType.REQUEST:
            if task.sender == "human" or "product idea" in task.subject.lower():
                return await self._handle_new_idea(task)
            else:
                return await self._handle_agent_request(task)
        
        elif task.task_type == TaskType.CLARIFICATION_RESPONSE:
            return await self._handle_clarification_response(task)
        
        elif task.task_type == TaskType.FEEDBACK:
            return await self._handle_feedback(task)
        
        elif task.task_type == TaskType.QUESTION:
            return await self._handle_question(task)
        
        else:
            # Default handling
            return TaskResult(success=True)
    
    async def _handle_new_idea(self, task: Task) -> TaskResult:
        """Handle a new product idea"""
        idea = task.content
        
        # Store the idea in memory
        self.memory.project_context = f"Product Idea: {idea}"
        
        # Think through the idea and create requirements
        requirements_prompt = f"""
Analyze this product idea and create a clear requirements document:

IDEA: {idea}

Create a requirements document with:
1. **Overview**: Brief description of what we're building
2. **Goals**: What problem does this solve? What's the value?
3. **MVP Scope**: What's the minimum viable product? (Keep it small!)
4. **User Stories**: 3-5 key user stories in format:
   - As a [user], I want [feature] so that [benefit]
   - Acceptance Criteria: [list of criteria]
5. **Out of Scope**: What are we NOT building in MVP?
6. **Open Questions**: Any clarifications needed from the human?

Be concise but complete. Focus on MVP.
"""
        
        requirements_content = await self.think(requirements_prompt)
        
        # Create requirements artifact
        requirements_artifact = Artifact(
            name="requirements.md",
            artifact_type=ArtifactType.REQUIREMENTS,
            content=requirements_content,
            file_path="docs/requirements.md",
            language="markdown",
            created_by=self.role,
            owner=self.role,
            description="Product requirements and user stories",
        )
        
        # Check if we need clarification
        needs_clarification = "open questions" in requirements_content.lower() and "?" in requirements_content
        
        result = TaskResult(
            success=True,
            artifacts_created=[requirements_artifact],
            decision_made=(
                "Initial requirements",
                "Created MVP requirements",
                "Focused on core functionality for initial version",
            ),
        )
        
        # If questions, ask human
        if needs_clarification:
            # Extract questions from the requirements
            question = await self._extract_questions(requirements_content)
            if question:
                result.needs_clarification = True
                result.clarification_question = question
                return result
        
        # Otherwise, hand off to Architect
        handoff_task = self.create_task(
            recipient=AgentRole.ARCHITECT,
            task_type=TaskType.REQUEST,
            subject="Requirements Ready for Design",
            content=f"""
The Product Manager has completed the initial requirements. Please review and create a technical design.

REQUIREMENTS:
{requirements_content}

Please:
1. Review the requirements for technical feasibility
2. Create a system design
3. Define the technical architecture
4. If you have concerns about requirements, let me know

When design is ready, hand off to Developer.
""",
            priority=Priority.HIGH,
            payload={"requirements_artifact_id": str(requirements_artifact.id)},
        )
        
        result.outgoing_tasks.append(handoff_task)
        self._requirements_ready = True
        
        return result
    
    async def _extract_questions(self, content: str) -> Optional[str]:
        """Extract questions from content to ask the human"""
        extract_prompt = f"""
From this requirements document, extract any open questions that need human clarification.
Format them as a clear, numbered list.
If there are no real questions, respond with "NO_QUESTIONS".

Document:
{content}

Questions for the human:
"""
        
        response = await self.think(extract_prompt)
        
        if "NO_QUESTIONS" in response.upper():
            return None
        
        return response
    
    async def _handle_clarification_response(self, task: Task) -> TaskResult:
        """Handle response to a clarification request"""
        answer = task.content
        
        # Update memory with the clarification
        self.memory.add_learning(f"Human clarified: {answer}")
        
        # Update requirements with the new information
        current_reqs = self._get_requirements_artifact()
        if current_reqs:
            update_prompt = f"""
Update the requirements based on this human clarification:

Current Requirements:
{current_reqs.content}

Human's Answer:
{answer}

Provide the updated requirements document incorporating this information.
Remove or answer any questions that have been addressed.
"""
            
            updated_content = await self.think(update_prompt)
            current_reqs.update_content(updated_content, self.role)
            
            # Check if ready to hand off
            if "open questions" not in updated_content.lower() or "?" not in updated_content:
                # Hand off to Architect
                handoff_task = self.create_task(
                    recipient=AgentRole.ARCHITECT,
                    task_type=TaskType.REQUEST,
                    subject="Requirements Ready for Design",
                    content=f"""
Requirements have been clarified and are ready for technical design.

REQUIREMENTS:
{updated_content}

Please create the technical design.
""",
                    priority=Priority.HIGH,
                )
                
                return TaskResult(
                    success=True,
                    artifacts_updated=[current_reqs],
                    outgoing_tasks=[handoff_task],
                )
            
            return TaskResult(success=True, artifacts_updated=[current_reqs])
        
        return TaskResult(success=True)
    
    async def _handle_agent_request(self, task: Task) -> TaskResult:
        """Handle requests from other agents"""
        # Evaluate the request
        evaluation = await self.evaluate_request(task)
        
        if evaluation == ResponseType.ACCEPT:
            # Process the request
            response_content = await self.think(
                f"Respond to this request from {task.sender}: {task.content}",
                context=task.payload.get("context", ""),
            )
            
            response = task.create_response(
                sender=self.role,
                response_type=ResponseType.ACCEPT,
                content=response_content,
            )
            
            return TaskResult(success=True, response_task=response)
        
        elif evaluation == ResponseType.COUNTER:
            counter_content = await self.think(
                f"I need to counter-propose this request: {task.content}\nExplain my alternative proposal.",
            )
            
            response = task.create_response(
                sender=self.role,
                response_type=ResponseType.COUNTER,
                content=counter_content,
            )
            
            return TaskResult(success=True, response_task=response)
        
        else:
            response = task.create_response(
                sender=self.role,
                response_type=evaluation,
                content=f"Unable to process request: {evaluation.value}",
            )
            return TaskResult(success=True, response_task=response)
    
    async def _handle_feedback(self, task: Task) -> TaskResult:
        """Handle feedback from other agents"""
        self.memory.add_learning(f"Feedback from {task.sender}: {task.content}")
        
        # If feedback requires requirements update
        if "requirement" in task.content.lower() or "change" in task.content.lower():
            current_reqs = self._get_requirements_artifact()
            if current_reqs:
                # Consider updating requirements
                update_prompt = f"""
Consider this feedback and decide if requirements need updating:

Current Requirements:
{current_reqs.content}

Feedback from {task.sender}:
{task.content}

If updates are needed, provide the updated requirements.
If no updates needed, explain why and say "NO_UPDATE_NEEDED".
"""
                
                response = await self.think(update_prompt)
                
                if "NO_UPDATE_NEEDED" not in response.upper():
                    current_reqs.update_content(response, self.role)
                    return TaskResult(success=True, artifacts_updated=[current_reqs])
        
        return TaskResult(success=True)
    
    async def _handle_question(self, task: Task) -> TaskResult:
        """Handle questions from other agents"""
        answer = await self.think(
            f"Answer this question from {task.sender}: {task.content}",
        )
        
        response = task.create_response(
            sender=self.role,
            response_type=ResponseType.ACCEPT,
            content=answer,
        )
        
        return TaskResult(success=True, response_task=response)
    
    def _get_requirements_artifact(self) -> Optional[Artifact]:
        """Get the current requirements artifact"""
        reqs = self.project.get_artifacts_by_type(ArtifactType.REQUIREMENTS)
        return reqs[0] if reqs else None
