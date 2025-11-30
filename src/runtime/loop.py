from __future__ import annotations
"""Agent Runtime - manages the async execution of all agents"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Awaitable

from ..core.models import Project, AgentRole, Task, TaskType, Priority
from ..core.ports.llm import LLMPort
from ..core.ports.storage import StoragePort
from ..agents.base import BaseAgent
from ..agents.pm import ProductManagerAgent
from ..agents.architect import ArchitectAgent
from ..agents.developer import DeveloperAgent
from ..agents.tester import TesterAgent
from .queue import MessageBus
from .status import StatusAggregator


@dataclass
class SystemCommand:
    """Human intervention command"""
    command: str  # pause, resume, inject, redirect, status, shutdown
    target_agent: Optional[AgentRole] = None
    payload: str = ""


class AgentRuntime:
    """
    Manages the execution of all agents for a project.
    
    - Spawns agent coroutines
    - Routes messages between agents
    - Handles human intervention
    - Provides status updates
    """
    
    def __init__(
        self,
        project: Project,
        llm: LLMPort,
        storage: StoragePort,
        on_clarification_needed: Optional[Callable[[Task], Awaitable[str]]] = None,
        on_milestone_reached: Optional[Callable[[str, str], Awaitable[bool]]] = None,
        on_status_update: Optional[Callable[[str], None]] = None,
    ):
        self.project = project
        self.llm = llm
        self.storage = storage
        self.message_bus = MessageBus()
        
        # Callbacks for human interaction
        self.on_clarification_needed = on_clarification_needed
        self.on_milestone_reached = on_milestone_reached
        self.on_status_update = on_status_update
        
        # Create agents
        self.agents: dict[AgentRole, BaseAgent] = {}
        self._create_agents()
        
        # Status aggregator
        self.status = StatusAggregator(project)
        
        # Control
        self._running = False
        self._shutdown_requested = False
        self._command_queue: asyncio.Queue[SystemCommand] = asyncio.Queue()
    
    def _create_agents(self) -> None:
        """Create all agent instances"""
        agent_classes = {
            AgentRole.PM: ProductManagerAgent,
            AgentRole.ARCHITECT: ArchitectAgent,
            AgentRole.DEVELOPER: DeveloperAgent,
            AgentRole.TESTER: TesterAgent,
        }
        
        for role, agent_class in agent_classes.items():
            self.agents[role] = agent_class(
                role=role,
                llm=self.llm,
                project=self.project,
                message_bus=self.message_bus,
            )
    
    async def start(self, initial_idea: str) -> None:
        """Start the runtime with an initial product idea"""
        self._running = True
        
        # Initialize project with the idea
        self.project.original_idea = initial_idea
        self.project.name = initial_idea[:50]  # Will be refined by PM
        self.project.initialize_agents()
        
        # Create initial task for PM
        initial_task = Task(
            sender="human",
            recipient=AgentRole.PM,
            task_type=TaskType.REQUEST,
            priority=Priority.HIGH,
            subject="New Product Idea",
            content=f"""
A human has submitted a new product idea for the AI Company to build:

{initial_idea}

Please analyze this idea and:
1. Refine it into clear requirements
2. Create user stories with acceptance criteria
3. Identify any clarifications needed from the human
4. When requirements are ready, hand off to the Architect

Remember: Focus on MVP scope. Keep it simple and achievable.
""",
        )
        
        # Send to PM
        await self.message_bus.send(initial_task)
        
        # Start agent loops and monitoring
        await asyncio.gather(
            self._run_agents(),
            self._run_command_processor(),
            self._run_status_monitor(),
            self._run_clarification_handler(),
            self._run_convergence_checker(),
        )
    
    async def _run_agents(self) -> None:
        """Run all agent loops concurrently"""
        agent_tasks = [
            agent.run()
            for agent in self.agents.values()
        ]
        
        await asyncio.gather(*agent_tasks, return_exceptions=True)
    
    async def _run_command_processor(self) -> None:
        """Process human intervention commands"""
        while not self._shutdown_requested:
            try:
                command = await asyncio.wait_for(
                    self._command_queue.get(),
                    timeout=0.5,
                )
                await self._handle_command(command)
            except asyncio.TimeoutError:
                continue
    
    async def _handle_command(self, cmd: SystemCommand) -> None:
        """Handle a system command"""
        if cmd.command == "pause":
            if cmd.target_agent:
                self.agents[cmd.target_agent].pause()
            else:
                for agent in self.agents.values():
                    agent.pause()
        
        elif cmd.command == "resume":
            if cmd.target_agent:
                self.agents[cmd.target_agent].resume()
            else:
                for agent in self.agents.values():
                    agent.resume()
        
        elif cmd.command == "inject":
            if cmd.target_agent:
                self.agents[cmd.target_agent].inject_guidance(cmd.payload)
            else:
                for agent in self.agents.values():
                    agent.inject_guidance(cmd.payload)
        
        elif cmd.command == "shutdown":
            self._shutdown_requested = True
            for agent in self.agents.values():
                agent.shutdown()
        
        elif cmd.command == "status":
            if self.on_status_update:
                self.on_status_update(self.status.get_summary())
    
    async def _run_status_monitor(self) -> None:
        """Periodically update status"""
        while not self._shutdown_requested:
            # Update agent queue counts
            for role, agent in self.agents.items():
                self.project.agents[role].inbox_count = agent.queue.inbox_count
                self.project.agents[role].outbox_count = agent.queue.outbox_count
            
            # Save project state periodically
            await self.storage.save_project(self.project)
            
            # Emit status update
            if self.on_status_update:
                self.on_status_update(self.status.get_summary())
            
            await asyncio.sleep(2.0)
    
    async def _run_clarification_handler(self) -> None:
        """Handle clarification requests from agents"""
        while not self._shutdown_requested:
            if self.project.pending_clarification:
                task = self.project.pending_clarification
                
                if self.on_clarification_needed:
                    # Get human response
                    answer = await self.on_clarification_needed(task)
                    
                    # Create response task
                    response = self.project.provide_clarification(answer)
                    
                    # Send to the agent that asked
                    await self.message_bus.send(response)
            
            await asyncio.sleep(0.5)
    
    async def _run_convergence_checker(self) -> None:
        """Check for project convergence (all agents signed off)"""
        while not self._shutdown_requested:
            if self.project.all_agents_signed_off():
                # All agents have signed off - project is ready
                if self.on_status_update:
                    self.on_status_update("✅ All agents signed off! Project ready for delivery.")
                
                self.project.mark_delivered()
                await self.storage.save_project(self.project)
                
                # Shutdown
                await self.send_command(SystemCommand(command="shutdown"))
            
            await asyncio.sleep(1.0)
    
    async def send_command(self, command: SystemCommand) -> None:
        """Send a command to the runtime"""
        await self._command_queue.put(command)
    
    def get_dashboard_data(self):
        """Get current dashboard data"""
        recent = [
            m for m in self.project.activity_log[-10:]
        ]
        return self.status.get_dashboard_data(recent)
    
    async def stop(self) -> None:
        """Stop the runtime gracefully"""
        await self.send_command(SystemCommand(command="shutdown"))
