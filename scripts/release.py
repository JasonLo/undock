# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "typer>=0.12.0",
#     "rich>=13.0.0",
# ]
# ///
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()
app = typer.Typer(help="Safe release manager for uv projects.")


class Increment(str, Enum):
    major = "major"
    minor = "minor"
    patch = "patch"


class ReleaseError(Exception):
    pass


def run(cmd: list[str], capture: bool = True) -> str:
    """Run a command and return output, raising ReleaseError on failure."""
    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, check=True)
        return result.stdout.strip() if capture else ""
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Error running {' '.join(cmd)}[/bold red]")
        if e.stderr:
            console.print(f"[red]{e.stderr.strip()}[/red]")
        raise ReleaseError(f"Command failed: {' '.join(cmd)}") from e


def get_push_target() -> tuple[str, str]:
    """Return (remote, branch) for pushing, derived from git config."""
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    try:
        remote = run(["git", "config", f"branch.{branch}.remote"])
    except ReleaseError:
        remote = "origin"
        console.print("[yellow]⚠️ No tracking remote configured, defaulting to 'origin'.[/yellow]")
    return remote, branch


def verify_git_state() -> None:
    """Ensure the repo is clean and synced with remote."""
    console.print("🔍 [blue]Checking git status...[/blue]")

    # 1. Check for uncommitted changes (staged or unstaged)
    status = run(["git", "status", "--porcelain"])
    if status:
        console.print("[bold red]❌ Working directory is not clean![/bold red]")
        console.print("Please commit or stash your changes before releasing:")
        console.print(f"[yellow]{status}[/yellow]")
        raise ReleaseError("Working directory is not clean")

    # 2. Check if local is synced with remote
    run(["git", "fetch"])
    local_hash = run(["git", "rev-parse", "HEAD"])
    try:
        remote_hash = run(["git", "rev-parse", "@{u}"])
    except ReleaseError:
        console.print(
            "[yellow]⚠️ No upstream branch found. Skipping remote sync check.[/yellow]"
        )
        return

    if local_hash != remote_hash:
        ahead = run(["git", "rev-list", "HEAD", "--not", "@{u}", "--count"])
        behind = run(["git", "rev-list", "@{u}", "--not", "HEAD", "--count"])

        if int(behind) > 0:
            console.print(
                f"[bold red]❌ You are behind the remote by {behind} commits.[/bold red] Pull first."
            )
            raise ReleaseError(f"Behind remote by {behind} commits")
        if int(ahead) > 0:
            console.print(
                f"[bold red]❌ You have {ahead} unpushed commits.[/bold red] Push them first."
            )
            raise ReleaseError(f"Ahead of remote by {ahead} commits")

    console.print("[green]✅ Git state is clean and synced.[/green]")


@app.command()
def main(
    increment: Annotated[Increment, typer.Argument(help="Version component to bump")] = Increment.patch,
) -> None:
    try:
        # Phase 1: Guards
        verify_git_state()
        remote, branch = get_push_target()

        # Phase 2: Bump
        console.print(f"🚀 [blue]Bumping version ({increment.value})...[/blue]")
        run(["uv", "version", "--bump", increment.value], capture=False)
        new_version: str = run(["uv", "version", "--short"])
        tag_name: str = f"v{new_version}"

        # Phase 3: Commit and Tag
        console.print(f"📦 [blue]Creating tag {tag_name}...[/blue]")
        run(["git", "add", "pyproject.toml"])
        if Path("uv.lock").exists():
            run(["git", "add", "uv.lock"])
        run(["git", "commit", "-m", f"chore: release {tag_name}"], capture=False)
        run(["git", "tag", "-a", tag_name, "-m", tag_name], capture=False)

        # Phase 4: Push (roll back local commit and tag on failure)
        console.print(f"⬆️  [blue]Pushing to {remote}/{branch}...[/blue]")
        try:
            run(["git", "push", remote, branch], capture=False)
            run(["git", "push", remote, tag_name], capture=False)
        except ReleaseError:
            console.print("[yellow]⚠️ Push failed — rolling back local commit and tag...[/yellow]")
            subprocess.run(["git", "tag", "-d", tag_name], capture_output=True)
            subprocess.run(["git", "reset", "--soft", "HEAD~1"], capture_output=True)
            raise

        console.print(f"\n[bold green]✨ Successfully released {tag_name}![/bold green]")

    except ReleaseError:
        sys.exit(1)


if __name__ == "__main__":
    app()
