# Copyright (c) 2022-2024, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, List

from utils.statefile import Statefile


class IsaacLabContainerInterface:
    """
    Interface for managing Isaac Lab containers.

    Attributes:
        context_dir: The context directory for Docker operations, where the necessary YAML/.env/Dockerfiles files are located.
        target: The targeted stage for the container. Defaults to "base".
        statefile: An instance of the Statefile class to manage state variables.
        container_name: The name of the container.
        image_name: The name of the image.
        add_yamls: YAML files to be included in the Docker compose command.
        add_env_files: Environment files to be included in the Docker compose command.
        dot_vars: Dictionary of environment variables loaded from .env files.
        environ: Dictionary of environment variables for subprocesses.
    """

    def __init__(
        self,
        dir: Path,
        target: str = "base",
        statefile: None | Statefile = None,
        yamls: list[str] | None = None,
        envs: list[str] | None = None,
    ):
        """
        Initialize the IsaacLabContainerInterface with the given parameters.

        Args:
            context_dir : The directory for Docker operations.
            statefile : An instance of the Statefile class to manage state variables. If not provided, initializes a Statefile(path=self.dir/.container.yaml).
            profile : The profile name for the container. Defaults to "base".
            yamls : A list of yamls to extend docker-compose.yaml. They will be extended in the order they are provided.
            envs : A list of envs to extend .env.base. They will be extended in the order they are provided.
        """
        self.dir = dir
        self.compose_cfgs = Path(self.dir/ "cfgs")
        if not self.compose_cfgs.is_dir():
            raise FileNotFoundError(f"Required directory {self.compose_cfgs} was not found.")
        if statefile is None:
            self.statefile = Statefile(path=self.dir / ".container.cfg")
        else:
            self.statefile = statefile
        self.target = target
        if self.target == "isaaclab":
            # Silently correct from isaaclab to base,
            # because isaaclab is a commonly passed arg
            # but not a real target
            self.target = "base"
        self.container_name = f"isaac-lab-{self.target}"
        self.image_name = f"isaac-lab-{self.target}:latest"
        self.environ = os.environ
        self.environ.update({"TARGET": self.target})
        self.resolve_compose_cfg(yamls, envs)
        # self.load_dot_vars()

    def resolve_compose_cfg(self, yamls: list[str] | None = None, envs: list[str] | None = None):
        """
        Resolve the compose configuration by setting up YAML files and environment files for the Docker compose command.

        Args:
            yamls: A list of yamls to extend base.yaml. They will be extended in the order they are provided.
            envs: A list of envs to extend .env.base. They will be extended in the order they are provided.
        """
        # stage_dep_dict = self.parse_dockerfile()
        # self.yamls = [self.compose_cfgs.joinpath("isaac-lab/isaac-lab.yaml")]
        self.yamls = [f"{self.target}.yaml"]
        self.env_files = []

        # if self.dev_volumes:
        #     self.yamls += ["dev-volumes.yaml"]
        # if self.workstation_volumes:
        #     self.yamls += ["workstation-volumes.yaml"]
        # self.yamls = ["base.yaml"]
        # self.env_files = [".env.base"]
        # Determine if there is a chain of stage dependencies
        # from this stage, otherwise it's referencing a different Dockerfile
        # if self.target in stage_dep_dict.keys():
        #     for stage in stage_dep_dict[self.target]:
        #         self.yamls += [f"{stage}.yaml"]
        #         self.env_files += [f".env.{stage}"]

                # if stage != "base":
                # if os.path.isfile(os.path.join(self.dir, f"{stage}.yaml")):
                # self.yamls += [f"{stage}.yaml"]
                # if os.path.isfile(os.path.join(self.dir, f".env.{stage}")):
                # self.env_files += [f".env.{stage}"]

        if yamls is not None:
            self.yamls += yamls

        if envs is not None:
            self.env_files += envs

    @property
    def dot_vars(self):
        self.load_dot_vars()
        return self._dot_vars
    
    def search_compose_cfgs(self, file):
        hint = None
        if file.endswith(".yaml"):
            hint, _ = file.split(".")
        elif file.startswith(".env"):
            env_tup = file.split(".")
            # If the .env file had a follow (.env.followup).
            # extract and use it as a search hint
            if len(env_tup) == 3:
                _, _, hint = env_tup
        
        if not hint is None:
            hint_path = os.path.join(self.compose_cfgs, f"{hint}", file)
            if os.path.isfile(hint_path):
                return hint_path
        
        # Brute force search self.compose_cfgs if the hint path failed
        for root, _, files in os.walk(self.compose_cfgs):
            if file in files:
                return os.path.abspath(os.path.join(root, file))
            
        raise FileNotFoundError(f"Couldn't find required {file} under the compose_cfgs directory {self.compose_cfgs}")
        
    
    def load_dot_vars(self):
        """
        Load environment variables from .env files into a dictionary.

        The environment variables are read in order and overwritten if there are name conflicts,
        mimicking the behavior of Docker compose.
        """
        self._dot_vars: dict[str, Any] = {}
        abs_env_files = [self.search_compose_cfgs(file) for file in self.env_files]
        for i in range(len(abs_env_files)):
            with open(self.dir / abs_env_files[i]) as f:
                self._dot_vars.update(dict(line.strip().split("=", 1) for line in f if "=" in line))

    def add_env_files(self) -> List[str]:
        """
        Put self.env_files into a state suitable for the docker compose CLI, with '--env-file' between
        every argument

        Returns:
            [str]: A list of strings, with '--env-file' first and then interpolated between the strings of
                   self.env_files
        """
        abs_env_files = [self.search_compose_cfgs(file) for file in self.env_files]
        return [abs_env_files[int(i / 2)] if i % 2 == 1 else "--env-file" for i in range(len(abs_env_files) * 2)]

    def add_yamls(self) -> List[str]:
        """
        Put self.yamls into a state suitable for the docker compose CLI, with '--file' between
        every argument

        Returns:
            [str]: A list of strings, with '--file' first and then interpolated between the strings of
                   self.yamls
        """
        abs_yaml_files =  [self.search_compose_cfgs(file) for file in self.yamls]
        return [abs_yaml_files[int(i / 2)] if i % 2 == 1 else "--file" for i in range(len(abs_yaml_files) * 2)]

    def is_container_running(self) -> bool:
        """
        Check if the container is running.

        If the container is not running, return False.

        Returns:
            bool: True if the container is running, False otherwise.
        """
        status = subprocess.run(
            ["docker", "container", "inspect", "-f", "{{.State.Status}}", self.container_name],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return status == "running"

    def does_image_exist(self) -> bool:
        """
        Check if the Docker image exists.

        If the image does not exist, return False.

        Returns:
            bool: True if the image exists, False otherwise.
        """
        result = subprocess.run(["docker", "image", "inspect", self.image_name], capture_output=True, text=True, check=False)
        return result.returncode == 0

    def start(self):
        """
        Build and start the Docker container using the Docker compose 'up' command.
        """
        print(f"[INFO] Building the docker image and starting the container {self.container_name} in the background...")
        subprocess.run(
            ["docker", "compose"]
            + self.add_yamls()
            + self.add_env_files()
            + ["up", "--detach", "--build", "--remove-orphans"],
            check=False,
            cwd=self.dir,
            env=self.environ,
        )

    def build(self):
        """
        Build the Docker container using the Docker compose 'build' command.
        """
        print(f"[INFO] Building the docker image {self.image_name}...")
        subprocess.run(
            ["docker", "compose"] + self.add_yamls() + self.add_env_files() + ["build"],
            check=False,
            cwd=self.dir,
            env=self.environ,
        )

    def enter(self):
        """
        Enter the running container by executing a bash shell.

        Raises:
            RuntimeError: If the container is not running.
        """
        if self.is_container_running():
            subprocess.run([
                "docker",
                "exec",
                "--interactive",
                "--tty",
                "-e",
                f"DISPLAY={os.environ['DISPLAY']}",
                f"{self.container_name}",
                "bash",
            ])
        else:
            raise RuntimeError(f"The container '{self.container_name}' is not running")

    def stop(self):
        """
        Stop the running container using the Docker compose command.

        Raises:
            RuntimeError: If the container is not running.
        """
        if self.is_container_running():
            print(f"[INFO] Stopping the launched docker container {self.container_name}...")
            subprocess.run(
                ["docker", "compose"] + self.add_yamls() + self.add_env_files() + ["down"],
                check=False,
                cwd=self.dir,
                env=self.environ,
            )
        else:
            raise RuntimeError(f"Can't stop container '{self.container_name}' as it is not running.")

    def copy(self, output_dir: Path | None = None):
        """
        Copy artifacts from the running container to the host machine.

        Args:
            output_dir: The directory to copy the artifacts to. Defaults to self.dir.

        Raises:
            RuntimeError: If the container is not running.
        """
        if self.is_container_running():
            print(f"[INFO] Copying artifacts from the 'isaac-lab-{self.container_name}' container...")
            if output_dir is None:
                output_dir = self.dir
            output_dir = output_dir.joinpath("artifacts")
            if not output_dir.is_dir():
                output_dir.mkdir()
            artifacts = {
                Path(self.dot_vars["DOCKER_ISAACLAB_PATH"]).joinpath("logs"): output_dir.joinpath("logs"),
                Path(self.dot_vars["DOCKER_ISAACLAB_PATH"]).joinpath("docs/_build"): output_dir.joinpath("docs"),
                Path(self.dot_vars["DOCKER_ISAACLAB_PATH"]).joinpath("data_storage"): output_dir.joinpath(
                    "data_storage"
                ),
            }
            for container_path, host_path in artifacts.items():
                print(f"\t -{container_path} -> {host_path}")
            for path in artifacts.values():
                shutil.rmtree(path, ignore_errors=True)
            for container_path, host_path in artifacts.items():
                subprocess.run(
                    [
                        "docker",
                        "cp",
                        f"isaac-lab-{self.target}:{container_path}/",
                        f"{host_path}",
                    ],
                    check=False,
                )
            print("\n[INFO] Finished copying the artifacts from the container.")
        else:
            raise RuntimeError(f"The container '{self.container_name}' is not running")

    def config(self, output_yaml: Path | None = None):
        """
        Generate a docker-compose.yaml from the passed yamls, .envs, and either print to the
        terminal or create a yaml at output_yaml

        Args:
            output_yaml: The absolute path of the yaml file to write the output to, if any. Defaults
            to None, and simply prints to the terminal
        """
        print("[INFO] Configuring the passed options into a yaml...")
        if output_yaml is not None:
            output = ["--output", output_yaml]
        else:
            output = []
        subprocess.run(
            ["docker", "compose"] + self.add_yamls() + self.add_env_files() + ["config"] + output,
            check=False,
            cwd=self.dir,
            env=self.environ,
        )

    def parse_dockerfile(self, file_name: str | None = None):
        """
        Parses a Dockerfile and returns a dictionary with each final stage as a key and a list of its dependency chain as the value.

        Args:
        - file_name: The name of the Dockerfile.

        Returns:
        - Dict[str, List[str]]: A dictionary where each key is a final stage and the value is a list of stages in the order of dependency.
        """
        stages = []
        stage_dependencies = defaultdict(list)

        # Regular expressions to match stages and COPY/FROM instructions
        stage_pattern = re.compile(r"FROM\s+([^\s]+)(?:\s+AS\s+([^\s]+))?", re.IGNORECASE)
        copy_pattern = re.compile(r"COPY\s+--from=([^\s]+)", re.IGNORECASE)

        # Read the Dockerfile content
        if file_name is None:
            file_name = os.path.join(self.dir, "Dockerfile")
            if not os.path.isfile(file_name):
                raise FileNotFoundError(
                    "No Dockerfile was passed for parsing, and a Dockerfile couldn't be found at the passed context"
                    " root."
                )
        with open(file_name) as file:
            dockerfile_content = file.read()

        # Parse the Dockerfile
        for line in dockerfile_content.splitlines():
            stage_match = stage_pattern.match(line)
            copy_match = copy_pattern.search(line)

            if stage_match:
                base_image = stage_match.group(1)
                stage_name = stage_match.group(2)
                current_stage = stage_name if stage_name else base_image
                stages.append(current_stage)

                # Add dependency if the base image is a stage name
                if base_image in stages:
                    stage_dependencies[current_stage].append(base_image)

            if copy_match:
                stage_dependencies[current_stage].append(copy_match.group(1))

        # Organize into a dictionary based on dependencies
        result = {}
        for stage in stages:
            chain = []
            to_visit = [stage]
            while to_visit:
                current = to_visit.pop(0)
                if current not in chain:
                    chain.append(current)
                    to_visit = stage_dependencies[current] + to_visit
            result[stage] = chain[::-1]

        return result