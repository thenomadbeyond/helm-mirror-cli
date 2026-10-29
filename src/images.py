# mirror_tool/images.py
import subprocess
import re
import os

import yaml

from auth import registry_env


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
    images = set()

    # Try YAML parsing first — handles all known Helm image reference patterns
    try:
        docs = list(yaml.safe_load_all(rendered_yaml))
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
):
    succeeded = []
    failed = []

    def _process(img):
        if save_dir is not None:
            tar_path = save_image_as_tar(img, save_dir, tools, dry_run, insecure, auth)
            print(f"[INFO] {img} -> {tar_path}")
            return tar_path

        new = rewrite_image(img, registry, prefix)
        if skip_existing and not dry_run and _image_exists(new, tools, insecure, auth):
            print(f"[SKIP] {img} -> {new} (already exists)")
            return new
        print(f"[INFO] {img} -> {new}")
        if not dry_run:
            copy_image(img, new, tools, insecure, auth)
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


def save_image_as_tar(image, output_dir, tools, dry_run=False, insecure=False, auth=None):
    os.makedirs(output_dir, exist_ok=True)
    tar_path = os.path.join(output_dir, _image_to_filename(image))

    if dry_run:
        return tar_path

    tool = tools["copy"]
    tls = ["--tls-verify=false"] if insecure else []
    with registry_env(tool, **(auth or {})) as env:
        if tool == "crane":
            cmd = ["crane", "pull"] + (["--insecure"] if insecure else [])
            subprocess.run(cmd + ["--format=tarball", image, tar_path], check=True, env=env)
        elif tool == "skopeo":
            cmd = ["skopeo", "copy"] + (["--src-tls-verify=false"] if insecure else [])
            subprocess.run(cmd + [f"docker://{image}", f"docker-archive:{tar_path}"], check=True, env=env)
        elif tool == "docker":
            if insecure:
                _warn_docker_insecure()
            subprocess.run(["docker", "pull", image], check=True, env=env)
            subprocess.run(["docker", "save", image, "-o", tar_path], check=True, env=env)
        else:
            subprocess.run(["podman", "pull"] + tls + [image], check=True, env=env)
            subprocess.run(["podman", "save", image, "-o", tar_path], check=True, env=env)

    return tar_path


def copy_image(src, dst, tools, insecure=False, auth=None):
    tool = tools["copy"]
    tls = ["--tls-verify=false"] if insecure else []
    with registry_env(tool, **(auth or {})) as env:
        if tool == "crane":
            cmd = ["crane", "copy"] + (["--insecure"] if insecure else [])
            subprocess.run(cmd + [src, dst], check=True, env=env)
        elif tool == "skopeo":
            cmd = ["skopeo", "copy"]
            if insecure:
                cmd += ["--src-tls-verify=false", "--dest-tls-verify=false"]
            subprocess.run(cmd + [f"docker://{src}", f"docker://{dst}"], check=True, env=env)
        elif tool == "docker":
            if insecure:
                _warn_docker_insecure()
            subprocess.run(["docker", "pull", src], check=True, env=env)
            subprocess.run(["docker", "tag", src, dst], check=True, env=env)
            subprocess.run(["docker", "push", dst], check=True, env=env)
        else:
            subprocess.run(["podman", "pull"] + tls + [src], check=True, env=env)
            subprocess.run(["podman", "tag", src, dst], check=True, env=env)
            subprocess.run(["podman", "push"] + tls + [dst], check=True, env=env)


def write_image_list(images, path):
    with open(path, "w") as f:
        for img in images:
            f.write(img + "\n")
