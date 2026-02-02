import asyncio
from abc import ABC, abstractmethod
from typing import Any, Tuple


class RuntimeEnvironment(ABC):
    @abstractmethod
    async def run_command(self, command: str, cwd: str = None) -> Tuple[bool, str, Any]:
        """Execute a command in this environment."""
        pass


class LocalEnvironment(RuntimeEnvironment):
    async def run_command(self, command: str, cwd: str = None) -> Tuple[bool, str, Any]:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await proc.communicate()
            return (
                proc.returncode == 0,
                stdout.decode().strip() + "\n" + stderr.decode().strip(),
                None,
            )
        except Exception as e:
            return False, str(e), None


class DockerEnvironment(RuntimeEnvironment):
    def __init__(self, service_name: str, compose_file: str = "docker-compose.yml"):
        self.service_name = service_name
        self.compose_file = compose_file
        # Standardization: Always use modern 'docker compose' (V2)
        self._compose_cmd = "docker compose"

    async def run_command(self, command: str, cwd: str = None) -> Tuple[bool, str, Any]:
        full_command = (
            f'{self._compose_cmd} exec -T {self.service_name} sh -c "{command}"'
        )
        success, output, artifact = await self._safe_exec(full_command)

        if not success and "not found" in output.lower():
            if "docker" in output.lower():
                output = (
                    "Docker Compose not found. Please ensure Docker (V2) is installed. gateway. "
                    "Aether Lens has dropped support for legacy 'docker-compose' (V1)."
                )

        return success, output, artifact

    async def _safe_exec(self, full_command: str) -> Tuple[bool, str, Any]:
        try:
            proc = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return (
                proc.returncode == 0,
                stdout.decode().strip() + "\n" + stderr.decode().strip(),
                None,
            )
        except Exception as e:
            return False, str(e), None


class K8sEnvironment(RuntimeEnvironment):
    def __init__(self, pod_name: str, namespace: str, container: str = "aether-lens"):
        self.pod_name = pod_name
        self.namespace = namespace
        self.container = container

    async def run_command(self, command: str, cwd: str = None) -> Tuple[bool, str, Any]:
        # kubectl exec -n [namespace] [pod] -c [container] -- [command]
        full_command = f'kubectl exec -n {self.namespace} {self.pod_name} -c {self.container} -- sh -c "{command}"'
        try:
            proc = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            success = proc.returncode == 0
            output = stdout.decode().strip() + "\n" + stderr.decode().strip()

            if (
                not success
                and "not found" in output.lower()
                and "kubectl" in output.lower()
            ):
                output = "kubectl not found. Please ensure Kubernetes CLI is installed and in your PATH."

            return success, output, None
        except Exception as e:
            return False, str(e), None
