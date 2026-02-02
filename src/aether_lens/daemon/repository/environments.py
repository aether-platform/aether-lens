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

    async def run_command(self, command: str, cwd: str = None) -> Tuple[bool, str, Any]:
        # docker-compose exec [service] [command]
        # Note: we use -T to disable pseudo-terminal since we are in non-interactive mode
        full_command = f'docker-compose exec -T {self.service_name} sh -c "{command}"'
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
            return (
                proc.returncode == 0,
                stdout.decode().strip() + "\n" + stderr.decode().strip(),
                None,
            )
        except Exception as e:
            return False, str(e), None
