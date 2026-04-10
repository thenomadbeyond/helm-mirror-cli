
# mirror_tool/helm.py
import subprocess
import tempfile
import os


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(result.stderr)
    return result.stdout


def pull_chart(chart, version=None, repo_url=None):
    if os.path.isdir(chart):
        return chart

    tmp = tempfile.mkdtemp()

    # If repo URL is provided, add it temporarily
    if repo_url:
        repo_name = "tmp-repo"
        run(["helm", "repo", "add", repo_name, repo_url])
        chart = f"{repo_name}/{chart}"

    cmd = ["helm", "pull", chart, "--untar", "--untardir", tmp]
    if version:
        cmd += ["--version", version]

    run(cmd)

    return os.path.join(tmp, os.listdir(tmp)[0])


def render_chart(chart_path, values=None):
    cmd = ["helm", "template", chart_path]
    if values:
        cmd += ["-f", values]

    return run(cmd)


def push_chart(chart_path, target_registry, chart_target=None):
    run(["helm", "package", chart_path])

    tgz = [f for f in os.listdir(".") if f.endswith(".tgz")][-1]

    repo = chart_target if chart_target else f"oci://{target_registry}"

    if not repo.startswith("oci://"):
        repo = f"oci://{repo}"

    run(["helm", "push", tgz, repo])