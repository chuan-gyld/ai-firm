from __future__ import annotations
"""Main entry point for AI Company"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.prompt import Prompt, Confirm

from .core.models import Project, Task, Message, AgentRole
from .core.ports.llm import LLMMessage
from .adapters.llm_litellm import LiteLLMAdapter
from .adapters.storage_sqlite import SQLiteStorageAdapter
from .adapters.cli.dashboard import TerminalDashboard, print_welcome, print_delivered
from .adapters.cli.tui import AICompanyApp, run_tui
from .runtime.loop import AgentRuntime, SystemCommand


console = Console()


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """Load configuration from YAML file"""
    config_file = Path(config_path)
    
    if config_file.exists():
        with open(config_file) as f:
            return yaml.safe_load(f)
    
    # Default config (using Zhipu GLM-4)
    return {
        "llm": {
            "model": "openai/glm-4-plus",
            "api_base": "https://open.bigmodel.cn/api/paas/v4",
            "fallback_model": None,
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        "project": {
            "output_dir": "./output",
            "state_db": "./state.db",
        },
    }


async def handle_clarification(task: Task) -> str:
    """Handle clarification request from an agent"""
    console.print()
    console.print(f"[bold yellow]📝 Clarification Needed[/bold yellow]")
    console.print(f"[dim]From: {task.sender}[/dim]")
    console.print()
    console.print(task.content)
    console.print()
    
    answer = Prompt.ask("[cyan]Your answer[/cyan]")
    return answer


async def handle_milestone(name: str, description: str) -> bool:
    """Handle milestone verification"""
    console.print()
    console.print(f"[bold blue]🏁 Milestone Reached: {name}[/bold blue]")
    console.print(f"[dim]{description}[/dim]")
    console.print()
    
    approved = Confirm.ask("[cyan]Approve this milestone?[/cyan]", default=True)
    return approved


def handle_status_update(summary: str) -> None:
    """Handle status update (for logging)"""
    # Status updates are handled by the dashboard
    pass


async def run_interactive(idea: str, config: dict) -> None:
    """Run the AI Company with interactive TUI"""
    
    # Initialize adapters
    llm = LiteLLMAdapter(
        default_model=config["llm"]["model"],
        api_base=config["llm"].get("api_base"),
        fallback_model=config["llm"].get("fallback_model"),
        temperature=config["llm"].get("temperature", 0.7),
        max_tokens=config["llm"].get("max_tokens", 4096),
    )
    
    storage = SQLiteStorageAdapter(
        db_path=config["project"].get("state_db", "./state.db"),
        output_dir=config["project"].get("output_dir", "./output"),
    )
    
    # Create project
    project = Project()
    project.name = idea[:50] if len(idea) > 50 else idea
    project.original_idea = idea
    project.output_directory = str(storage.output_dir / str(project.id))
    project.initialize_agents()
    
    # Variables to hold runtime and app references
    runtime: Optional[AgentRuntime] = None
    app: Optional[AICompanyApp] = None
    output_files: list[str] = []
    
    # Callbacks for TUI actions
    async def on_pause():
        if runtime:
            await runtime.send_command(SystemCommand(command="pause"))
    
    async def on_resume():
        if runtime:
            await runtime.send_command(SystemCommand(command="resume"))
    
    async def on_inject(guidance: str):
        if runtime:
            await runtime.send_command(SystemCommand(
                command="inject",
                payload=guidance,
            ))
    
    async def on_quit():
        if runtime:
            await runtime.stop()
    
    # Create TUI app
    app = AICompanyApp(
        project=project,
        on_pause=on_pause,
        on_resume=on_resume,
        on_inject=on_inject,
        on_quit=on_quit,
    )
    
    # Clarification handler that uses the TUI
    clarification_response: Optional[str] = None
    clarification_event = asyncio.Event()
    
    async def handle_clarification_tui(task: Task) -> str:
        nonlocal clarification_response
        clarification_event.clear()
        
        def on_response(answer: str):
            nonlocal clarification_response
            clarification_response = answer
            clarification_event.set()
        
        # Request clarification through TUI
        app.request_clarification(task, on_response)
        
        # Wait for response
        await clarification_event.wait()
        return clarification_response or ""
    
    # Status update handler
    def handle_status_tui(summary: str):
        pass  # TUI handles its own updates
    
    # Create runtime
    runtime = AgentRuntime(
        project=project,
        llm=llm,
        storage=storage,
        on_clarification_needed=handle_clarification_tui,
        on_milestone_reached=handle_milestone,
        on_status_update=handle_status_tui,
    )
    
    # Track runtime task and ready state
    runtime_task: Optional[asyncio.Task] = None
    tui_ready = False
    pending_activities: list[Task] = []
    
    # Activity logger
    def log_activity(task: Task):
        msg = Message.from_task(task)
        project.log_activity(task)
        if tui_ready:
            app.add_activity(msg)
        else:
            pending_activities.append(task)
    
    # Patch the message bus to log activities
    original_send = runtime.message_bus.send
    async def logged_send(task: Task):
        await original_send(task)
        log_activity(task)
    runtime.message_bus.send = logged_send
    
    async def run_runtime():
        """Run the agent runtime"""
        try:
            app.add_system_message(f"Starting AI Company with idea: {idea}", "green")
            app.add_system_message("PM is analyzing the idea...", "cyan")
            await runtime.start(idea)
        except asyncio.CancelledError:
            app.add_system_message("Runtime cancelled", "yellow")
        except Exception as e:
            app.add_system_message(f"Runtime error: {e}", "red")
            import traceback
            traceback.print_exc()
        finally:
            # Save final state
            await storage.save_project(project)
            
            # Write output files
            nonlocal output_files
            for artifact in project.artifacts.values():
                if artifact.file_path and artifact.content:
                    await storage.write_output_file(
                        project.id,
                        artifact.file_path,
                        artifact.content,
                    )
                    output_files.append(artifact.file_path)
            
            if project.state.value == "delivered":
                app.show_delivered(output_files)
    
    def start_runtime():
        """Start the runtime after TUI is ready"""
        nonlocal runtime_task, tui_ready
        tui_ready = True
        
        # Flush any pending activities
        for task in pending_activities:
            msg = Message.from_task(task)
            app.add_activity(msg)
        pending_activities.clear()
        
        runtime_task = asyncio.create_task(run_runtime())
        app.add_system_message("Runtime started", "green")
    
    # Set the callback to start runtime when TUI is ready
    app.set_on_ready(start_runtime)
    
    try:
        # Run the TUI (this blocks until quit)
        await app.run_async()
        
        # Cancel runtime if still running
        if runtime_task and not runtime_task.done():
            runtime_task.cancel()
            try:
                await runtime_task
            except asyncio.CancelledError:
                pass
        
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        raise
    
    # Print final summary to console after TUI exits
    if output_files:
        print_delivered(console, project, output_files)


async def run_simple(idea: str, config: dict) -> None:
    """Run a simplified version for quick testing"""
    
    console.print(f"\n[bold]🚀 Quick Mode - Processing idea...[/bold]\n")
    
    # Initialize LLM
    llm = LiteLLMAdapter(
        default_model=config["llm"]["model"],
        fallback_model=config["llm"].get("fallback_model"),
        temperature=config["llm"].get("temperature", 0.7),
    )
    
    storage = SQLiteStorageAdapter(
        db_path=config["project"].get("state_db", "./state.db"),
        output_dir=config["project"].get("output_dir", "./output"),
    )
    
    # Create project
    project = Project()
    project.name = idea[:50]
    project.original_idea = idea
    project.output_directory = str(storage.output_dir / str(project.id))
    project.initialize_agents()
    
    console.print("[green]✅ Quick mode not implemented - use interactive mode[/green]")


def main():
    """Main entry point"""
    print_welcome(console)
    
    # Load config
    config = load_config()
    
    # Get idea from command line or prompt
    if len(sys.argv) > 1:
        idea = " ".join(sys.argv[1:])
    else:
        console.print("[bold]Enter your product idea:[/bold]")
        idea = Prompt.ask("[cyan]Idea[/cyan]")
    
    if not idea.strip():
        console.print("[red]No idea provided. Exiting.[/red]")
        return
    
    # Run
    try:
        asyncio.run(run_interactive(idea, config))
    except KeyboardInterrupt:
        console.print("\n[yellow]Goodbye![/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
