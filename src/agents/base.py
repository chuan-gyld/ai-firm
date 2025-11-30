from __future__ import annotations
"""Base Agent - common logic for all agents (memory, inbox, judgment)"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from ..core.models import (
    AgentRole, AgentStatus, AgentState, AgentMemory,
    Task, TaskType, TaskStatus, Priority, ResponseType,
    Artifact, ArtifactType, Project,
)
from ..core.ports.llm import LLMPort, LLMMessage
from ..runtime.queue import TaskQueue, MessageBus


@dataclass
class TaskResult:
    """Result of processing a task"""
    success: bool = True
    response_task: Optional[Task] = None
    outgoing_tasks: list[Task] = field(default_factory=list)
    artifacts_created: list[Artifact] = field(default_factory=list)
    artifacts_updated: list[Artifact] = field(default_factory=list)
    decision_made: Optional[tuple[str, str, str]] = None  # (subject, choice, rationale)
    concern_raised: Optional[tuple[str, str]] = None  # (description, severity)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    sign_off: bool = False
    revoke_signoff: Optional[str] = None


class BaseAgent(ABC):
    """
    Base class for all AI agents.
    
    Each agent is modeled as a 'person' with:
    - Persistent memory across the project
    - Prioritized inbox for async work
    - Judgment to accept/reject/counter-propose
    - Owned documents they maintain
    """
    
    def __init__(
        self,
        role: AgentRole,
        llm: LLMPort,
        project: Project,
        message_bus: MessageBus,
    ):
        self.role = role
        self.llm = llm
        self.project = project
        self.message_bus = message_bus
        
        # Get or create agent state
        self.state = project.get_agent(role) or AgentState(role=role)
        project.agents[role] = self.state
        
        # Create task queue
        self.queue = TaskQueue(role)
        message_bus.register_agent(role, self.queue)
        
        # Control flags
        self._shutdown_requested = False
        self._paused = False
    
    @property
    def memory(self) -> AgentMemory:
        """Access agent's persistent memory"""
        return self.state.memory
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the role-specific system prompt"""
        pass
    
    @abstractmethod
    async def process_task(self, task: Task) -> TaskResult:
        """Process a task - implemented by each agent type"""
        pass
    
    async def run(self) -> None:
        """Main agent loop - runs continuously until shutdown"""
        while not self._shutdown_requested:
            # Check if paused
            if self._paused:
                self.state.update_status(AgentStatus.PAUSED)
                await asyncio.sleep(0.5)
                continue
            
            # Get next task
            task = await self.queue.get_next()
            
            if task is None:
                self.state.update_status(AgentStatus.IDLE)
                self.state.current_task_id = None
                self.state.current_task_summary = ""
                await asyncio.sleep(0.3)
                continue
            
            # Process the task
            await self._process_task_wrapper(task)
        
        self.state.update_status(AgentStatus.IDLE)
    
    async def _process_task_wrapper(self, task: Task) -> None:
        """Wrapper around task processing with status updates"""
        self.state.start_task(task.id, task.subject or task.content[:50])
        self.state.inbox_count = self.queue.inbox_count
        
        try:
            task.mark_in_progress()
            result = await self.process_task(task)
            
            # Handle result
            await self._handle_task_result(task, result)
            
            task.mark_completed()
            self.state.complete_task()
            
        except Exception as e:
            print(f"[{self.role.value}] Error processing task: {e}")
            self.state.update_status(AgentStatus.IDLE)
            # Requeue with lower priority on error
            task.priority = Priority.LOW
            await self.queue.requeue(task)
    
    async def _handle_task_result(self, original_task: Task, result: TaskResult) -> None:
        """Handle the result of processing a task"""
        # Send response if needed
        if result.response_task:
            await self.message_bus.send(result.response_task)
            await self.queue.mark_sent(result.response_task)
        
        # Send outgoing tasks
        for task in result.outgoing_tasks:
            await self.message_bus.send(task)
            if task.requires_response:
                await self.queue.mark_sent(task)
        
        # Store artifacts
        for artifact in result.artifacts_created:
            self.project.add_artifact(artifact)
        
        for artifact in result.artifacts_updated:
            self.project.add_artifact(artifact)
        
        # Record decision
        if result.decision_made:
            subject, choice, rationale = result.decision_made
            self.memory.add_decision(subject, choice, rationale)
        
        # Record concern
        if result.concern_raised:
            description, severity = result.concern_raised
            self.memory.add_concern(description, severity)
        
        # Handle clarification request
        if result.needs_clarification and result.clarification_question:
            clarification_task = self.create_clarification_request(
                result.clarification_question,
                context=original_task.content,
            )
            self.project.request_clarification(clarification_task)
        
        # Handle sign-off
        if result.sign_off:
            self.state.sign_off()
        
        if result.revoke_signoff:
            self.state.revoke_signoff(result.revoke_signoff)
    
    def create_task(
        self,
        recipient: AgentRole | str,
        task_type: TaskType,
        subject: str,
        content: str,
        priority: Priority = Priority.MEDIUM,
        payload: dict[str, Any] | None = None,
        requires_response: bool = True,
    ) -> Task:
        """Create a task to send to another agent"""
        return Task(
            sender=self.role,
            recipient=recipient,
            task_type=task_type,
            priority=priority,
            subject=subject,
            content=content,
            payload=payload or {},
            requires_response=requires_response,
        )
    
    def create_clarification_request(
        self,
        question: str,
        context: str = "",
    ) -> Task:
        """Create a clarification request for the human"""
        return Task(
            sender=self.role,
            recipient="human",
            task_type=TaskType.CLARIFICATION_REQUEST,
            priority=Priority.HIGH,
            subject=f"Clarification needed from {self.role.display_name}",
            content=question,
            payload={"context": context},
            requires_response=True,
        )
    
    async def evaluate_request(self, task: Task) -> ResponseType:
        """
        Evaluate an incoming request using judgment.
        Returns how the agent should respond.
        """
        # Build evaluation prompt
        messages = [
            LLMMessage(role="system", content=self.get_system_prompt()),
            LLMMessage(role="user", content=f"""
You are evaluating a request from {task.sender}.

Request: {task.subject}
Details: {task.content}

Based on your role and expertise, evaluate this request:
1. Is this feasible given the current project state?
2. Is this consistent with existing decisions and designs?
3. Does this meet your professional standards?
4. Is the effort proportional to the value?

Your current context:
{self.memory.get_context_summary()}

Respond with one of:
- ACCEPT: You'll do this as requested
- COUNTER: You propose a modification (explain what and why)
- REJECT: You can't/won't do this (explain why)
- CLARIFY: You need more information (list your questions)
- ESCALATE: This decision is beyond your authority

Just respond with the word and a brief explanation.
"""),
        ]
        
        response = await self.llm.complete(messages, temperature=0.3)
        content = response.content.upper()
        
        if "ACCEPT" in content:
            return ResponseType.ACCEPT
        elif "COUNTER" in content:
            return ResponseType.COUNTER
        elif "REJECT" in content:
            return ResponseType.REJECT
        elif "CLARIFY" in content:
            return ResponseType.CLARIFY
        elif "ESCALATE" in content:
            return ResponseType.ESCALATE
        else:
            return ResponseType.ACCEPT  # Default to accepting
    
    async def think(self, prompt: str, context: str = "") -> str:
        """Use LLM to think through a problem"""
        messages = [
            LLMMessage(role="system", content=self.get_system_prompt()),
            LLMMessage(role="user", content=f"""
{prompt}

Your current context and memory:
{self.memory.get_context_summary()}

{f"Additional context: {context}" if context else ""}
"""),
        ]
        
        response = await self.llm.complete(messages)
        return response.content
    
    async def generate_artifact(
        self,
        artifact_type: ArtifactType,
        name: str,
        prompt: str,
        file_path: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Artifact:
        """Generate an artifact using LLM"""
        content = await self.think(prompt)
        
        artifact = Artifact(
            name=name,
            artifact_type=artifact_type,
            content=content,
            file_path=file_path,
            language=language,
            created_by=self.role,
            owner=self.role,
        )
        
        return artifact
    
    def pause(self) -> None:
        """Pause agent processing"""
        self._paused = True
        self.state.update_status(AgentStatus.PAUSED)
    
    def resume(self) -> None:
        """Resume agent processing"""
        self._paused = False
    
    def shutdown(self) -> None:
        """Request agent shutdown"""
        self._shutdown_requested = True
    
    def inject_guidance(self, guidance: str) -> None:
        """Inject human guidance into agent context"""
        self.memory.project_context += f"\n\n[HUMAN GUIDANCE]: {guidance}"
        self.memory.add_learning(f"Human guidance received: {guidance}")
