import shutil
from pathlib import Path
from typing import Optional


class ToolResolver:
    """Handles discovery and validation of external tools and executables."""

    @staticmethod
    def find_executable(name: str) -> Optional[str]:
        """Find an executable in the system path."""
        exe_path = shutil.which(name)
        if exe_path:
            return str(exe_path)

        # Fallback for common locations if which fails
        common_paths = [
            Path("/usr/local/bin") / name,
            Path("/usr/bin") / name,
            Path("/bin") / name,
        ]
        for path in common_paths:
            if path.exists():
                return str(path)
        return None

    @staticmethod
    async def check_tool_presence(command: str) -> tuple[bool, str]:
        """Check if the required tool is available using Path/shutil."""
        if not command:
            return True, ""

        words = command.split()
        first_word = words[0]

        # Handling 'docker compose' as a single tool concept
        if first_word == "docker" and len(words) > 1 and words[1] == "compose":
            if ToolResolver.find_executable("docker"):
                return True, ""
            return False, "Command 'docker' (required for 'docker compose') not found."

        if ToolResolver.find_executable(first_word):
            return True, ""
        return False, f"Command '{first_word}' not found in PATH."
