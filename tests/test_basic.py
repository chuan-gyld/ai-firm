"""Basic tests for AI Company"""
from __future__ import annotations

import pytest
from uuid import uuid4

from src.core.models import (
    Project, AgentRole, AgentStatus, AgentState, AgentMemory,
    Task, TaskType, Priority, Message, ResponseType,
    Artifact, ArtifactType,
)
from src.runtime.queue import TaskQueue, MessageBus


class TestAgentModels:
    """Test agent-related models"""
    
    def test_agent_role_display_names(self):
        assert AgentRole.PM.display_name == "Product Manager"
        assert AgentRole.ARCHITECT.display_name == "Architect"
        assert AgentRole.DEVELOPER.display_name == "Developer"
        assert AgentRole.TESTER.display_name == "Tester"
    
    def test_agent_status_emojis(self):
        assert AgentStatus.WORKING.emoji == "🟢"
        assert AgentStatus.WAITING.emoji == "🟡"
        assert AgentStatus.IDLE.emoji == "🔵"
        assert AgentStatus.PAUSED.emoji == "🔴"
    
    def test_agent_memory(self):
        memory = AgentMemory()
        
        # Add decision
        decision = memory.add_decision(
            subject="Test decision",
            choice="Option A",
            rationale="Because it's simpler",
        )
        assert len(memory.decision_history) == 1
        assert decision.subject == "Test decision"
        
        # Add concern
        concern = memory.add_concern("Potential issue", "high")
        assert len(memory.active_concerns) == 1
        assert concern.severity == "high"
        
        # Get active concerns
        active = memory.get_active_concerns()
        assert len(active) == 1
        
        # Resolve concern
        memory.resolve_concern(concern.id)
        active = memory.get_active_concerns()
        assert len(active) == 0
    
    def test_agent_state(self):
        state = AgentState(role=AgentRole.PM)
        assert state.status == AgentStatus.IDLE
        assert not state.signed_off
        
        # Update status
        state.update_status(AgentStatus.WORKING)
        assert state.status == AgentStatus.WORKING
        
        # Start task
        task_id = uuid4()
        state.start_task(task_id, "Test task")
        assert state.current_task_id == task_id
        assert state.status == AgentStatus.WORKING
        
        # Complete task
        state.complete_task()
        assert state.current_task_id is None
        assert state.tasks_completed == 1


class TestTaskModels:
    """Test task-related models"""
    
    def test_task_creation(self):
        task = Task(
            sender=AgentRole.PM,
            recipient=AgentRole.ARCHITECT,
            task_type=TaskType.REQUEST,
            subject="Design system",
            content="Please design the system",
        )
        assert task.priority == Priority.MEDIUM
        assert task.status.value == "pending"
    
    def test_task_priority_comparison(self):
        high = Task(priority=Priority.HIGH)
        medium = Task(priority=Priority.MEDIUM)
        low = Task(priority=Priority.LOW)
        
        assert high < medium < low
    
    def test_task_create_response(self):
        original = Task(
            sender=AgentRole.PM,
            recipient=AgentRole.ARCHITECT,
            subject="Request",
            content="Please do something",
        )
        
        response = original.create_response(
            sender=AgentRole.ARCHITECT,
            response_type=ResponseType.ACCEPT,
            content="Done!",
        )
        
        assert response.recipient == AgentRole.PM
        assert response.parent_task_id == original.id
        assert response.subject == "Re: Request"
    
    def test_message_from_task(self):
        task = Task(
            sender=AgentRole.PM,
            recipient=AgentRole.ARCHITECT,
            subject="Test message",
        )
        
        message = Message.from_task(task)
        assert message.from_agent == "pm"
        assert message.to_agent == "architect"
        assert message.summary == "Test message"


class TestProjectModels:
    """Test project-related models"""
    
    def test_project_initialization(self):
        project = Project(name="Test Project")
        project.initialize_agents()
        
        assert len(project.agents) == 4
        assert AgentRole.PM in project.agents
        assert AgentRole.ARCHITECT in project.agents
    
    def test_project_artifacts(self):
        project = Project()
        
        artifact = Artifact(
            name="requirements.md",
            artifact_type=ArtifactType.REQUIREMENTS,
            content="# Requirements",
        )
        
        project.add_artifact(artifact)
        
        assert len(project.artifacts) == 1
        reqs = project.get_artifacts_by_type(ArtifactType.REQUIREMENTS)
        assert len(reqs) == 1
    
    def test_project_signoff(self):
        project = Project()
        project.initialize_agents()
        
        assert not project.all_agents_signed_off()
        
        for agent in project.agents.values():
            agent.signed_off = True
        
        assert project.all_agents_signed_off()


class TestTaskQueue:
    """Test task queue functionality"""
    
    @pytest.mark.asyncio
    async def test_queue_priority_order(self):
        queue = TaskQueue(AgentRole.PM)
        
        # Add tasks in wrong order
        low = Task(priority=Priority.LOW, subject="Low")
        high = Task(priority=Priority.HIGH, subject="High")
        medium = Task(priority=Priority.MEDIUM, subject="Medium")
        
        await queue.enqueue(low)
        await queue.enqueue(high)
        await queue.enqueue(medium)
        
        # Should get them back in priority order
        first = await queue.get_next()
        assert first.subject == "High"
        
        second = await queue.get_next()
        assert second.subject == "Medium"
        
        third = await queue.get_next()
        assert third.subject == "Low"
    
    @pytest.mark.asyncio
    async def test_queue_empty(self):
        queue = TaskQueue(AgentRole.PM)
        
        result = await queue.get_next()
        assert result is None


class TestMessageBus:
    """Test message bus functionality"""
    
    @pytest.mark.asyncio
    async def test_message_routing(self):
        bus = MessageBus()
        
        pm_queue = TaskQueue(AgentRole.PM)
        arch_queue = TaskQueue(AgentRole.ARCHITECT)
        
        bus.register_agent(AgentRole.PM, pm_queue)
        bus.register_agent(AgentRole.ARCHITECT, arch_queue)
        
        # Send message from PM to Architect
        task = Task(
            sender=AgentRole.PM,
            recipient=AgentRole.ARCHITECT,
            subject="Test",
        )
        
        await bus.send(task)
        
        # Architect should have the task
        received = await arch_queue.get_next()
        assert received.subject == "Test"
        
        # PM should not
        pm_task = await pm_queue.get_next()
        assert pm_task is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
