# mirror_tool/runtime.py
import shutil


def detect_tools():
    tools = {}

    if not shutil.which("helm"):
        raise Exception("helm not found")

    # Prefer daemonless tools that don't require a running service.
    # skopeo is preferred over docker/podman because it copies images
    # between registries without needing a container runtime daemon.
    if shutil.which("crane"):
        tools["copy"] = "crane"
    elif shutil.which("skopeo"):
        tools["copy"] = "skopeo"
    elif shutil.which("docker"):
        tools["copy"] = "docker"
    elif shutil.which("podman"):
        tools["copy"] = "podman"
    else:
        raise Exception("No container tool found (crane/skopeo/docker/podman)")

    if shutil.which("yq"):
        tools["yq"] = True

    return tools
