# mirror_tool/images.py
import subprocess
import re
import os
import time
import fnmatch

import yaml

from auth import registry_env


class _StringLoader(yaml.SafeLoader):
    """SafeLoader that keeps numbers as strings.

    Otherwise an unquoted `tag: 1.10` is parsed as the float 1.1 and the wrong
    image tag would be mirrored.
    """


_StringLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers
         if tag not in ("tag:yaml.org,2002:float", "tag:yaml.org,2002:int")]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}

# Image refs come from untrusted charts and end up as command arguments, so
# only accept plausible references (this also rejects values starting with "-").
_IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]*$")


def _walk_for_images(node, images):
    """Recursively walk a parsed YAML node and collect image references.

    Handles three common Helm patterns:
    1. Standard k8s:  image: "registry/name:tag"
    2. Nested dict:   image: {repository: ..., tag: ...}
    3. NVIDIA/sibling: repository: ..., image: name, version: tag  (same dict level)
    """
    if isinstance(node, list):
        for item in node:
            _walk_for_images(item, images)
    elif isinstance(node, dict):
        repo = node.get("repository")
        img_val = node.get("image")
        tag = node.get("version") or node.get("tag")

        if repo and isinstance(repo, str) and img_val and isinstance(img_val, str):
            # Pattern 3: sibling repository + image [+ version/tag]
            ref = f"{repo.rstrip('/')}/{img_val}"
            if tag is not None:
                ref = f"{ref}:{tag}"
            images.add(ref)
        elif img_val:
            if isinstance(img_val, str) and img_val.strip():
                # Pattern 1: image: "full/ref:tag"
                images.add(img_val.strip())
            elif isinstance(img_val, dict):
                # Pattern 2: image: {repository: ..., tag: ...}
                n_repo = img_val.get("repository")
                n_tag = img_val.get("tag") or img_val.get("version")
                if n_repo and isinstance(n_repo, str):
                    ref = n_repo.rstrip("/")
                    if n_tag is not None:
                        ref = f"{ref}:{n_tag}"
                    images.add(ref)

        # Recurse into all nested structures
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk_for_images(value, images)


def extract_images(rendered_yaml, tools):
    return _filter_valid(_extract_images(rendered_yaml, tools))


def _filter_valid(images):
    valid = set()
    for img in images:
        if _IMAGE_REF.match(img):
            valid.add(img)
        else:
            print(f"[WARN] Ignoring invalid image reference: {img!r}")
    return valid


def filter_excluded(images, patterns):
    """Drop images matching any fnmatch pattern (e.g. 'docker.io/bitnami/*')."""
    kept = set()
    for img in images:
        hit = next((p for p in patterns if fnmatch.fnmatch(img, p)), None)
        if hit:
            print(f"[SKIP] {img} (excluded by {hit!r})")
        else:
            kept.add(img)
    return kept


def _extract_images(rendered_yaml, tools):
    images = set()

    # Try YAML parsing first — handles all known Helm image reference patterns
    try:
        docs = list(yaml.load_all(rendered_yaml, Loader=_StringLoader))
        _walk_for_images(docs, images)
        print("[INFO] Using YAML parsing for image extraction")
        return images
    except Exception as exc:
        print(f"[WARN] YAML parsing failed ({exc}), falling back to yq/regex")

    # yq fallback (standard image: "string" only)
    if tools.get("yq"):
        try:
            result = subprocess.run(
                ["yq", ".. | .image? // empty"],
                input=rendered_yaml,
                text=True,
                capture_output=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                if line.strip():
                    images.add(line.strip().strip('"'))
            print("[INFO] Using yq for image extraction")
            return images
        except Exception:
            print("[WARN] yq failed, falling back to regex")

    # Regex last resort
    pattern = re.compile(r"image:\s*([^\s]+)")
    for line in rendered_yaml.splitlines():
        m = pattern.search(line)
        if m:
            images.add(m.group(1))

    return images


def _run_retry(cmd, env, retries):
    """Run a command, retrying transient failures with exponential backoff."""
    for attempt in range(retries + 1):
        try:
            return subprocess.run(cmd, check=True, env=env)
        except subprocess.CalledProcessError:
            if attempt == retries:
                raise
            delay = 2 ** (attempt + 1)
            print(f"[WARN] {cmd[0]} {cmd[1]} failed, retrying in {delay}s ({attempt + 1}/{retries})")
            time.sleep(delay)


def _image_exists(image, tools, insecure=False, auth=None):
    """Return True when the image already exists in the registry."""
    tool = tools.get("copy")
    if tool == "crane":
        cmd = ["crane", "manifest", image]
        if insecure:
            cmd.append("--insecure")
    elif tool == "skopeo":
        cmd = ["skopeo", "inspect", f"docker://{image}"]
        if insecure:
            cmd.append("--tls-verify=false")
    else:
        return False
    with registry_env(tool, **(auth or {})) as env:
        return subprocess.run(cmd, capture_output=True, env=env).returncode == 0


def mirror_images(
    images,
    registry,
    prefix,
    tools,
    dry_run=False,
    save_dir=None,
    insecure=False,
    auth=None,
    parallel=1,
    skip_existing=False,
    retries=0,
):
    succeeded = []
    failed = []

    def _process(img):
        if save_dir is not None:
            tar_path = save_image_as_tar(img, save_dir, tools, dry_run, insecure, auth, retries)
            print(f"[INFO] {img} -> {tar_path}")
            return tar_path

        new = rewrite_image(img, registry, prefix)
        if skip_existing and not dry_run and _image_exists(new, tools, insecure, auth):
            print(f"[SKIP] {img} -> {new} (already exists)")
            return new
        print(f"[INFO] {img} -> {new}")
        if not dry_run:
            copy_image(img, new, tools, insecure, auth, retries)
        return new

    if parallel > 1:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_img = {executor.submit(_process, img): img for img in images}
            for future in concurrent.futures.as_completed(future_to_img):
                img = future_to_img[future]
                try:
                    succeeded.append((img, future.result()))
                except Exception as exc:
                    print(f"[ERROR] {img}: {exc}")
                    failed.append((img, str(exc)))
    else:
        for img in images:
            try:
                succeeded.append((img, _process(img)))
            except Exception as exc:
                print(f"[ERROR] {img}: {exc}")
                failed.append((img, str(exc)))

    print("\n[INFO] Summary:")
    for src, dst in succeeded:
        print(f"  OK   {src} -> {dst}")
    for src, err in failed:
        print(f"  FAIL {src}: {err}")

    if failed:
        raise RuntimeError(
            f"{len(failed)} image(s) failed to mirror; "
            f"{len(succeeded)} succeeded."
        )

    return [dst for _, dst in succeeded]


def rewrite_image(image, registry, prefix):
    parts = image.split("/")

    if len(parts) > 1 and "." in parts[0]:
        parts = parts[1:]

    new = "/".join(parts)

    if prefix:
        new = f"{prefix}/{new}"

    return f"{registry}/{new}"


def _image_to_filename(image):
    """Convert an image reference to a safe tar filename."""
    safe = image.replace("/", "_").replace(":", "_")
    return f"{safe}.tar"


def _warn_docker_insecure():
    print(
        "[WARN] --insecure has no effect for docker at the command level. "
        "Add the registry to insecure-registries in /etc/docker/daemon.json."
    )


def save_image_as_tar(image, output_dir, tools, dry_run=False, insecure=False, auth=None, retries=0):
    os.makedirs(output_dir, exist_ok=True)
    tar_path = os.path.join(output_dir, _image_to_filename(image))

    if dry_run:
        return tar_path

    tool = tools["copy"]
    tls = ["--tls-verify=false"] if insecure else []
    with registry_env(tool, **(auth or {})) as env:
        if tool == "crane":
            cmd = ["crane", "pull"] + (["--insecure"] if insecure else [])
            _run_retry(cmd + ["--format=tarball", image, tar_path], env, retries)
        elif tool == "skopeo":
            cmd = ["skopeo", "copy"] + (["--src-tls-verify=false"] if insecure else [])
            _run_retry(cmd + [f"docker://{image}", f"docker-archive:{tar_path}"], env, retries)
        elif tool == "docker":
            if insecure:
                _warn_docker_insecure()
            _run_retry(["docker", "pull", image], env, retries)
            _run_retry(["docker", "save", image, "-o", tar_path], env, retries)
        else:
            _run_retry(["podman", "pull"] + tls + [image], env, retries)
            _run_retry(["podman", "save", image, "-o", tar_path], env, retries)

    return tar_path


def copy_image(src, dst, tools, insecure=False, auth=None, retries=0):
    tool = tools["copy"]
    tls = ["--tls-verify=false"] if insecure else []
    with registry_env(tool, **(auth or {})) as env:
        if tool == "crane":
            cmd = ["crane", "copy"] + (["--insecure"] if insecure else [])
            _run_retry(cmd + [src, dst], env, retries)
        elif tool == "skopeo":
            cmd = ["skopeo", "copy"]
            if insecure:
                cmd += ["--src-tls-verify=false", "--dest-tls-verify=false"]
            _run_retry(cmd + [f"docker://{src}", f"docker://{dst}"], env, retries)
        elif tool == "docker":
            if insecure:
                _warn_docker_insecure()
            _run_retry(["docker", "pull", src], env, retries)
            _run_retry(["docker", "tag", src, dst], env, retries)
            _run_retry(["docker", "push", dst], env, retries)
        else:
            _run_retry(["podman", "pull"] + tls + [src], env, retries)
            _run_retry(["podman", "tag", src, dst], env, retries)
            _run_retry(["podman", "push"] + tls + [dst], env, retries)


def write_image_list(images, path):
    with open(path, "w") as f:
        for img in images:
            f.write(img + "\n")
