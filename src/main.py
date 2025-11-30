from __future__ import annotations
"""Main entry point for AI Company"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.live import Live

from .core.models import Project, Task, Message, AgentRole
from .core.ports.llm import LLMMessage
from .adapters.llm_litellm import LiteLLMAdapter
from .adapters.storage_sqlite import SQLiteStorageAdapter
from .adapters.cli.dashboard import TerminalDashboard, print_welcome, print_delivered
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
    """Run the AI Company with a read-only Rich dashboard"""
    
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
    
    # Create dashboard
    dashboard = TerminalDashboard(project)
    output_files: list[str] = []
    
    # Create runtime
    runtime = AgentRuntime(
        project=project,
        llm=llm,
        storage=storage,
        on_clarification_needed=handle_clarification,
        on_milestone_reached=handle_milestone,
        on_status_update=handle_status_update,
    )
    
    # Activity logger - add to dashboard
    original_send = runtime.message_bus.send
    async def logged_send(task: Task):
        await original_send(task)
        msg = Message.from_task(task)
        project.log_activity(task)
        dashboard.add_activity(msg)
    runtime.message_bus.send = logged_send
    
    console.print(f"\n[bold green]🚀 Starting AI Company[/bold green]")
    console.print(f"[cyan]Idea:[/cyan] {idea}")
    console.print(f"[dim]Press Ctrl+C to stop[/dim]\n")
    
    async def run_with_dashboard():
        """Run the runtime with live dashboard updates"""
        runtime_task = asyncio.create_task(runtime.start(idea))
        
        try:
            # Use Rich Live for auto-updating display
            with Live(dashboard.render_dashboard(), refresh_per_second=1, console=console) as live:
                while not runtime._shutdown_requested:
                    live.update(dashboard.render_dashboard())
                    
                    # Check for convergence
                    if project.all_agents_signed_off():
                        break
                    
                    # Check if runtime finished
                    if runtime_task.done():
                        # Check for exception
                        try:
                            runtime_task.result()
                        except Exception as e:
                            console.print(f"\n[red]Runtime error: {e}[/red]")
                        break
                    
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        
        # Stop runtime if still running
        if not runtime_task.done():
            await runtime.stop()
            runtime_task.cancel()
            try:
                await runtime_task
            except asyncio.CancelledError:
                pass
    
    try:
        await run_with_dashboard()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        await runtime.stop()
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
    finally:
        # Save final state
        await storage.save_project(project)
    
    # Write output files
    for artifact in project.artifacts.values():
        if artifact.file_path and artifact.content:
            await storage.write_output_file(
                project.id,
                artifact.file_path,
                artifact.content,
            )
            output_files.append(artifact.file_path)
    
    # Print delivery summary
    if project.state.value == "delivered":
        print_delivered(console, project, output_files)
    else:
        console.print(f"\n[yellow]Project state: {project.state.value}[/yellow]")
        dashboard.print_summary()


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
