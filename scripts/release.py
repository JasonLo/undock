# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer>=0.12.0",
# ]
# ///
import subprocess
from typing import Annotated

import typer  # type: ignore

app = typer.Typer(help="Automated release manager for uv projects.")


def run(cmd: str) -> str:
    """Helper to run shell commands and return output."""
    return subprocess.check_output(cmd, shell=True, text=True).strip()


@app.command()
def main(
    increment: Annotated[str, typer.Argument(help="major, minor, or patch")] = "patch",
):
    # 1. Bump version and capture the NEW version number
    # uv version --bump returns the new version; --short gives just the number
    print(f"🚀 Bumping version ({increment})...")
    subprocess.run(["uv", "version", "--bump", increment], check=True)
    new_version = run("uv version --short")

    # 2. Git operations
    tag_name = f"v{new_version}"
    print(f"📦 Creating tag {tag_name}...")

    # Commit the version bump
    subprocess.run(["git", "add", "pyproject.toml"], check=True)
    subprocess.run(["git", "commit", "-m", f"chore: release {tag_name}"], check=True)

    # Create the tag
    subprocess.run(["git", "tag", "-a", tag_name, "-m", tag_name], check=True)

    # 3. Push
    print("⬆️  Pushing to origin...")
    subprocess.run(["git", "push", "origin", "main"], check=True)
    subprocess.run(["git", "push", "origin", tag_name], check=True)

    print(f"✅ Successfully released {tag_name}!")


if __name__ == "__main__":
    app()
