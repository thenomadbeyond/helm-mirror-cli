# mirror_tool/runtime.py
import shutil


def detect_tools():
    tools = {}

    if not shutil.which("helm"):
        raise Exception("helm not found")

    if shutil.which("crane"):
        tools["copy"] = "crane"
    elif shutil.which("docker"):
        tools["copy"] = "docker"
    elif shutil.which("podman"):
        tools["copy"] = "podman"
    else:
        raise Exception("No container tool found (crane/docker/podman)")

    if shutil.which("yq"):
        tools["yq"] = True

    return tools
