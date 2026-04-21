
# mirror_tool/helm.py
import subprocess
import tempfile
import os


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        raise Exception(f"Command failed: {cmd_str}\n{result.stderr.strip()}")
    return result.stdout


def pull_chart(chart, version=None, repo_url=None):
    if os.path.isdir(chart):
        return chart

    # Auto-detect when --chart is a repo URL instead of a chart name.
    # e.g. https://kubernetes-sigs.github.io/headlamp/  →  repo_url=..., chart="headlamp"
    if chart.startswith(("http://", "https://")) and not chart.endswith(".tgz"):
        repo_url = chart
        chart = chart.rstrip("/").rsplit("/", 1)[-1]
        print(f"[INFO] Detected repo URL — using chart name: {chart}")

    # mkdtemp creates the directory, but helm --untardir requires it to not
    # exist yet (it creates the dir itself). Delete it after reserving the path.
    tmp = tempfile.mkdtemp()
    os.rmdir(tmp)

    repo_added = None

    if repo_url:
        repo_name = "tmp-repo"
        run(["helm", "repo", "add", repo_name, repo_url])
        run(["helm", "repo", "update", repo_name])
        repo_added = repo_name
        chart = f"{repo_name}/{chart}"

    cmd = ["helm", "pull", chart, "--untar", "--untardir", tmp]
    if version:
        cmd += ["--version", version]

    try:
        run(cmd)
    finally:
        if repo_added:
            subprocess.run(
                ["helm", "repo", "remove", repo_added], capture_output=True
            )

    dirs = os.listdir(tmp)
    if not dirs:
        raise Exception(
            f"helm pull succeeded but no chart directory was found in {tmp}"
        )

    return os.path.join(tmp, sorted(dirs)[0])


def render_chart(chart_path, values=None):
    cmd = ["helm", "template", "helm-mirror", chart_path]
    if values:
        cmd += ["-f", values]

    return run(cmd)


def push_chart(chart_path, target_registry, chart_target=None):
    pkg_dir = tempfile.mkdtemp()
    run(["helm", "package", chart_path, "--destination", pkg_dir])

    tgz_files = [f for f in os.listdir(pkg_dir) if f.endswith(".tgz")]
    if not tgz_files:
        raise Exception(f"helm package produced no .tgz file in {pkg_dir}")
    tgz = os.path.join(pkg_dir, tgz_files[0])

    repo = chart_target if chart_target else f"oci://{target_registry}"
    if not repo.startswith("oci://"):
        repo = f"oci://{repo}"

    run(["helm", "push", tgz, repo])
    print(f"[INFO] Chart pushed: {os.path.basename(tgz)} -> {repo}")
    os.remove(tgz)


def save_chart(chart_path, output_dir="."):
    os.makedirs(output_dir, exist_ok=True)

    run(["helm", "package", chart_path, "--destination", output_dir])

    tgz_files = sorted(
        [f for f in os.listdir(output_dir) if f.endswith(".tgz")],
        key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
    )
    if not tgz_files:
        raise Exception(f"helm package produced no .tgz file in {output_dir}")
    tgz = os.path.join(output_dir, tgz_files[-1])
    print(f"[INFO] Chart saved: {tgz}")
