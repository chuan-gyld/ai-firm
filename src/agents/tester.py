from __future__ import annotations
"""Tester Agent - tests code and reports bugs"""

from typing import Optional

from ..core.models import (
    AgentRole, Task, TaskType, Priority, ResponseType,
    Artifact, ArtifactType, BugReport, Project,
)
from ..core.ports.llm import LLMPort
from ..runtime.queue import MessageBus
from .base import BaseAgent, TaskResult
from .prompts import TESTER_SYSTEM_PROMPT


class TesterAgent(BaseAgent):
    """
    Tester agent - ensures code quality.
    
    Responsibilities:
    - Review and test code from Developer
    - Create and execute test cases
    - Report bugs clearly
    - Verify bug fixes
    - Sign off on quality
    """
    
    def __init__(
        self,
        role: AgentRole,
        llm: LLMPort,
        project: Project,
        message_bus: MessageBus,
    ):
        super().__init__(role, llm, project, message_bus)
        self._bugs_found: list[BugReport] = []
        self._bugs_fixed: list[BugReport] = []
    
    def get_system_prompt(self) -> str:
        return TESTER_SYSTEM_PROMPT
    
    async def process_task(self, task: Task) -> TaskResult:
        """Process incoming tasks"""
        
        if task.task_type == TaskType.REQUEST:
            if "test" in task.subject.lower() or "implementation" in task.subject.lower():
                return await self._handle_test_request(task)
            else:
                return await self._handle_agent_request(task)
        
        elif task.task_type == TaskType.NOTIFICATION:
            if "fix" in task.subject.lower() or "bug" in task.subject.lower():
                return await self._handle_fix_notification(task)
            else:
                return await self._handle_notification(task)
        
        elif task.task_type == TaskType.RESPONSE:
            return await self._handle_response(task)
        
        else:
            return TaskResult(success=True)
    
    async def _handle_test_request(self, task: Task) -> TaskResult:
        """Test the implementation"""
        code_content = task.content
        
        # Store in memory
        self.memory.project_context = "Testing implementation"
        
        # Get requirements for reference
        requirements = self._get_requirements_content()
        
        # Create test plan
        test_plan_prompt = f"""
Create a test plan for this code based on the requirements:

REQUIREMENTS:
{requirements or "Not available - test based on code functionality"}

CODE TO TEST:
{code_content}

Create test cases that cover:
1. Happy path - normal usage
2. Edge cases - boundary conditions
3. Error handling - invalid inputs
4. Basic functionality for each feature

Format each test case as:
TEST: Name of test
SCENARIO: What we're testing
STEPS: How to test it
EXPECTED: Expected result
---
"""
        
        test_plan = await self.think(test_plan_prompt)
        
        # Create test plan artifact
        test_plan_artifact = Artifact(
            name="test_plan.md",
            artifact_type=ArtifactType.TEST_PLAN,
            content=test_plan,
            file_path="docs/test_plan.md",
            language="markdown",
            created_by=self.role,
            owner=self.role,
            description="Test plan with test cases",
        )
        
        # Execute tests (simulated - analyze code for issues)
        test_results_prompt = f"""
Execute these test cases mentally against the code and report results:

TEST PLAN:
{test_plan}

CODE:
{code_content}

For each test, determine:
- PASS: The code handles this correctly
- FAIL: There's a bug (describe it)

Also look for:
- Obvious bugs
- Missing error handling
- Code quality issues
- Potential runtime errors

Report format:
## Test Results

### Passed Tests
- Test name: reason it passes

### Failed Tests / Bugs Found
BUG: Title
SEVERITY: Critical/High/Medium/Low
DESCRIPTION: What's wrong
STEPS: How to reproduce
EXPECTED: What should happen
ACTUAL: What actually happens
---

If all tests pass and no bugs found, say "ALL TESTS PASSED - READY FOR SIGN-OFF"
"""
        
        test_results = await self.think(test_results_prompt)
        
        # Create test results artifact
        test_results_artifact = Artifact(
            name="test_results.md",
            artifact_type=ArtifactType.TEST_RESULT,
            content=test_results,
            file_path="docs/test_results.md",
            language="markdown",
            created_by=self.role,
            owner=self.role,
            description="Test execution results",
        )
        
        result = TaskResult(
            success=True,
            artifacts_created=[test_plan_artifact, test_results_artifact],
        )
        
        # Check if tests passed
        if "ALL TESTS PASSED" in test_results.upper() or "READY FOR SIGN-OFF" in test_results.upper():
            # All good - sign off
            result.sign_off = True
            result.decision_made = (
                "Quality sign-off",
                "Approved",
                "All tests passed, code meets quality standards",
            )
            
            # Notify that testing is complete
            notify_task = self.create_task(
                recipient=AgentRole.PM,
                task_type=TaskType.NOTIFICATION,
                subject="Testing Complete - Ready for Delivery",
                content="""
Testing is complete. All tests passed.

The Tester has signed off on quality.
Please verify requirements are met and proceed with delivery.
""",
                requires_response=False,
            )
            result.outgoing_tasks.append(notify_task)
            
            # Also notify Architect and Developer
            for role in [AgentRole.ARCHITECT, AgentRole.DEVELOPER]:
                result.outgoing_tasks.append(self.create_task(
                    recipient=role,
                    task_type=TaskType.NOTIFICATION,
                    subject="Testing Complete - Signed Off",
                    content="All tests passed. Tester has signed off on quality.",
                    requires_response=False,
                ))
        
        else:
            # Bugs found - report to Developer
            bugs = self._parse_bugs(test_results)
            self._bugs_found.extend(bugs)
            
            for bug in bugs:
                self.project.add_artifact(bug)
            
            result.artifacts_created.extend(bugs)
            result.revoke_signoff = f"Found {len(bugs)} bug(s) that need fixing"
            
            # Create bug fix request
            bug_fix_task = self.create_task(
                recipient=AgentRole.DEVELOPER,
                task_type=TaskType.REQUEST,
                subject=f"Bug Fix Required - {len(bugs)} issue(s) found",
                content=f"""
Testing found the following issues that need to be fixed:

{test_results}

Please fix these bugs and notify me when ready for re-test.
""",
                priority=Priority.HIGH,
            )
            result.outgoing_tasks.append(bug_fix_task)
        
        return result
    
    def _parse_bugs(self, test_results: str) -> list[BugReport]:
        """Parse bug reports from test results"""
        bugs = []
        
        current_bug = None
        
        for line in test_results.split("\n"):
            line = line.strip()
            if line.startswith("BUG:"):
                if current_bug:
                    bugs.append(current_bug)
                current_bug = BugReport(
                    name=line.replace("BUG:", "").strip(),
                )
            elif current_bug:
                if line.startswith("SEVERITY:"):
                    current_bug.severity = line.replace("SEVERITY:", "").strip().lower()
                elif line.startswith("DESCRIPTION:"):
                    current_bug.content = line.replace("DESCRIPTION:", "").strip()
                elif line.startswith("STEPS:"):
                    current_bug.steps_to_reproduce = line.replace("STEPS:", "").strip()
                elif line.startswith("EXPECTED:"):
                    current_bug.expected_behavior = line.replace("EXPECTED:", "").strip()
                elif line.startswith("ACTUAL:"):
                    current_bug.actual_behavior = line.replace("ACTUAL:", "").strip()
                elif line == "---":
                    bugs.append(current_bug)
                    current_bug = None
        
        if current_bug:
            bugs.append(current_bug)
        
        return bugs
    
    async def _handle_fix_notification(self, task: Task) -> TaskResult:
        """Handle notification that a bug fix is ready"""
        self.memory.add_learning(f"Bug fix received: {task.content[:100]}...")
        
        # Re-test the fix
        retest_prompt = f"""
A bug fix has been applied. Verify the fix:

FIX DETAILS:
{task.content}

For each bug that was supposedly fixed:
1. Verify the fix addresses the root cause
2. Check for any regression issues
3. Confirm the test now passes

If all fixes are verified, say "FIXES VERIFIED - ALL TESTS PASS"
If issues remain, describe them clearly.
"""
        
        retest_results = await self.think(retest_prompt)
        
        if "FIXES VERIFIED" in retest_results.upper() or "ALL TESTS PASS" in retest_results.upper():
            # Mark bugs as fixed
            for bug in self._bugs_found:
                bug.resolve("Fixed and verified")
                self._bugs_fixed.append(bug)
            self._bugs_found.clear()
            
            # Sign off
            return TaskResult(
                success=True,
                sign_off=True,
                decision_made=(
                    "Bug fixes verified",
                    "Approved",
                    "All bugs fixed and verified",
                ),
                outgoing_tasks=[
                    self.create_task(
                        recipient=AgentRole.PM,
                        task_type=TaskType.NOTIFICATION,
                        subject="Testing Complete - All Bugs Fixed",
                        content="All bugs have been fixed and verified. Ready for delivery.",
                        requires_response=False,
                    )
                ],
            )
        
        else:
            # Still have issues
            return TaskResult(
                success=True,
                outgoing_tasks=[
                    self.create_task(
                        recipient=AgentRole.DEVELOPER,
                        task_type=TaskType.REQUEST,
                        subject="Bug Fix Incomplete - Issues Remain",
                        content=f"The fix didn't fully resolve the issues:\n\n{retest_results}",
                        priority=Priority.HIGH,
                    )
                ],
            )
    
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
    
    async def _handle_notification(self, task: Task) -> TaskResult:
        """Handle notifications"""
        self.memory.add_learning(f"Notification from {task.sender}: {task.content[:100]}...")
        return TaskResult(success=True)
    
    async def _handle_response(self, task: Task) -> TaskResult:
        """Handle responses"""
        self.memory.add_learning(f"Response from {task.sender}: {task.content[:100]}...")
        return TaskResult(success=True)
    
    def _get_requirements_content(self) -> Optional[str]:
        """Get requirements for testing reference"""
        reqs = self.project.get_artifacts_by_type(ArtifactType.REQUIREMENTS)
        if reqs:
            return reqs[0].content
        return None
