from __future__ import annotations
"""Task Queue - prioritized inbox/outbox for agents"""

import asyncio
import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from ..core.models import Task, AgentRole, Priority


@dataclass(order=True)
class PrioritizedTask:
    """Wrapper for heap ordering: (priority, timestamp, task)"""
    priority: int
    timestamp: datetime
    task: Task = field(compare=False)
    
    @classmethod
    def from_task(cls, task: Task) -> "PrioritizedTask":
        return cls(
            priority=task.priority.value,
            timestamp=task.created_at,
            task=task,
        )


class TaskQueue:
    """
    Priority queue for agent tasks.
    
    Each agent has:
    - inbox: incoming tasks (prioritized)
    - outbox: tasks sent, awaiting response
    - wip: current work in progress
    - backlog: deferred items
    """
    
    def __init__(self, agent_role: AgentRole):
        self.agent_role = agent_role
        self._inbox: list[PrioritizedTask] = []
        self._outbox: dict[UUID, Task] = {}
        self._wip: Optional[Task] = None
        self._backlog: list[Task] = []
        self._lock = asyncio.Lock()
    
    async def enqueue(self, task: Task) -> None:
        """Add a task to the inbox"""
        async with self._lock:
            heapq.heappush(self._inbox, PrioritizedTask.from_task(task))
    
    async def get_next(self) -> Optional[Task]:
        """Get the highest priority non-blocked task"""
        async with self._lock:
            while self._inbox:
                prioritized = heapq.heappop(self._inbox)
                task = prioritized.task
                
                # Check if blocked (waiting for response to a related task)
                if self._is_blocked(task):
                    self._backlog.append(task)
                    continue
                
                return task
            
            # Check backlog for unblocked items
            unblocked = []
            still_blocked = []
            for task in self._backlog:
                if self._is_blocked(task):
                    still_blocked.append(task)
                else:
                    unblocked.append(task)
            
            self._backlog = still_blocked
            
            if unblocked:
                # Return highest priority unblocked task
                unblocked.sort(key=lambda t: (t.priority, t.created_at))
                return unblocked[0]
            
            return None
    
    def _is_blocked(self, task: Task) -> bool:
        """Check if task is blocked waiting for a response"""
        # If this is a response to something we sent, it's not blocked
        if task.parent_task_id and task.parent_task_id in self._outbox:
            # Clear the outbox entry since we got a response
            del self._outbox[task.parent_task_id]
            return False
        
        return False
    
    async def mark_sent(self, task: Task) -> None:
        """Track a task we sent that requires a response"""
        async with self._lock:
            if task.requires_response:
                self._outbox[task.id] = task
    
    async def set_wip(self, task: Optional[Task]) -> None:
        """Set current work in progress"""
        async with self._lock:
            self._wip = task
    
    async def get_wip(self) -> Optional[Task]:
        """Get current work in progress"""
        async with self._lock:
            return self._wip
    
    async def requeue(self, task: Task) -> None:
        """Put a task back in the queue"""
        async with self._lock:
            heapq.heappush(self._inbox, PrioritizedTask.from_task(task))
    
    async def requeue_with_delay(self, task: Task) -> None:
        """Put a task in backlog (lower priority)"""
        async with self._lock:
            self._backlog.append(task)
    
    @property
    def inbox_count(self) -> int:
        """Number of tasks in inbox"""
        return len(self._inbox)
    
    @property
    def outbox_count(self) -> int:
        """Number of pending responses"""
        return len(self._outbox)
    
    @property
    def backlog_count(self) -> int:
        """Number of deferred tasks"""
        return len(self._backlog)
    
    async def peek_inbox(self, limit: int = 5) -> list[Task]:
        """Peek at top items in inbox without removing"""
        async with self._lock:
            # Create a copy of the heap to peek
            items = sorted(self._inbox)[:limit]
            return [p.task for p in items]
    
    async def clear(self) -> None:
        """Clear all queues"""
        async with self._lock:
            self._inbox.clear()
            self._outbox.clear()
            self._wip = None
            self._backlog.clear()


class MessageBus:
    """
    Central message bus for inter-agent communication.
    Routes tasks between agent queues.
    """
    
    def __init__(self):
        self._queues: dict[AgentRole, TaskQueue] = {}
        self._broadcast_subscribers: list[TaskQueue] = []
        self._activity_log: list[Task] = []
        self._lock = asyncio.Lock()
    
    def register_agent(self, role: AgentRole, queue: TaskQueue) -> None:
        """Register an agent's queue"""
        self._queues[role] = queue
        self._broadcast_subscribers.append(queue)
    
    async def send(self, task: Task) -> None:
        """Send a task to its recipient"""
        async with self._lock:
            self._activity_log.append(task)
        
        recipient = task.recipient
        
        if recipient == "broadcast":
            # Send to all agents except sender
            for role, queue in self._queues.items():
                if role != task.sender:
                    await queue.enqueue(task)
        elif recipient == "human":
            # Human tasks are handled separately
            pass
        elif isinstance(recipient, AgentRole):
            if recipient in self._queues:
                await self._queues[recipient].enqueue(task)
        elif isinstance(recipient, str):
            # Try to find agent by role name
            try:
                role = AgentRole(recipient)
                if role in self._queues:
                    await self._queues[role].enqueue(task)
            except ValueError:
                pass
    
    async def get_recent_activity(self, limit: int = 20) -> list[Task]:
        """Get recent activity across all agents"""
        async with self._lock:
            return self._activity_log[-limit:]
    
    def get_queue(self, role: AgentRole) -> Optional[TaskQueue]:
        """Get an agent's queue"""
        return self._queues.get(role)
