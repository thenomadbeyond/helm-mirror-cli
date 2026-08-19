# mirror_tool/images.py
import subprocess
import re
import os
import tempfile
import base64
import json

import yaml


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


def _get_registry_from_image(image):
    """Extract registry hostname from image reference."""
    # Handle various image formats:
    # - registry/namespace/repo:tag
    # - namespace/repo:tag (defaults to docker.io)
    # - repo:tag (defaults to docker.io)
    # - registry:port/namespace/repo:tag
    if '/' not in image:
        # No slash, could be just repo or repo:tag
        if ':' in image and not image.startswith(('http://', 'https://')):
            # Might be repo:tag
            return 'docker.io'
        else:
            # Just repo (unlikely but handle)
            return 'docker.io'
    
    # Split on first '/' to get potential registry
    parts = image.split('/', 1)
    first_part = parts[0]
    
    # If first part contains a dot or colon, it's likely a registry
    if '.' in first_part or ':' in first_part:
        return first_part
    else:
        # No dot or colon in first part, so it's likely a namespace (e.g., library, bitnami)
        # Default to docker.io
        return 'docker.io'


def _create_docker_auth_config(username, password, registry=None):
    """Create a Docker-style auth config for the given credentials.
    
    Returns a tuple of (temp_dir_path, env_dict) where:
    - temp_dir_path: Path to temporary directory containing config.json
    - env_dict: Environment variables to set (e.g., {'DOCKER_CONFIG': temp_dir_path})
    """
    if not username and not password:
        return None, {}
    
    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix='helm-mirror-auth-')
    
    # Determine registry if not provided
    if registry is None:
        # We'll need to determine this from context - for now, require registry param
        # This function will be called from context where we know the image
        registry = 'docker.io'  # fallback
    
    # Create auth string
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    
    # Create Docker config structure
    config = {
        "auths": {
            registry: {
                "auth": auth
            }
        }
    }
    
    # Write config.json
    config_path = os.path.join(temp_dir, 'config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    # Return temp dir and environment variables
    return temp_dir, {"DOCKER_CONFIG": temp_dir}


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


def _image_exists(image, tools, insecure=False, ca_cert=None, username=None, password=None):
    """Return True when the image already exists in the registry."""
    copy_tool = tools.get("copy")
    env = os.environ.copy()
    
    # Handle CA certificate
    if ca_cert and copy_tool in ("crane", "skopeo"):
        env["SSL_CERT_FILE"] = ca_cert
    elif ca_cert and copy_tool in ("docker", "podman"):
        print(
            f"[WARN] --ca-cert is not supported for {copy_tool}. "
            "Configure the daemon's trust store for custom CAs."
        )
    
    # Handle authentication
    auth_temp_dir = None
    if username or password:
        # Determine registry for auth
        registry = _get_registry_from_image(image)
        auth_temp_dir, auth_env = _create_docker_auth_config(username, password, registry)
        if auth_temp_dir:
            env.update(auth_env)
    
    try:
        if copy_tool == "crane":
            cmd = ["crane", "manifest", image]
            if insecure:
                cmd.append("--insecure")
            return subprocess.run(cmd, capture_output=True, env=env).returncode == 0
        elif copy_tool == "skopeo":
            cmd = ["skopeo", "inspect", f"docker://{image}"]
            if insecure:
                cmd.append("--tls-verify=false")
            return subprocess.run(cmd, capture_output=True, env=env).returncode == 0
        return False
    finally:
        # Clean up temporary auth directory
        if auth_temp_dir and os.path.exists(auth_temp_dir):
            import shutil
            shutil.rmtree(auth_temp_dir, ignore_errors=True)


def mirror_images(
    images,
    registry,
    prefix,
    tools,
    dry_run=False,
    save_dir=None,
    insecure=False,
    ca_cert=None,
    username=None,
    password=None,
    parallel=1,
    skip_existing=False,
):
    succeeded = []
    failed = []

    def _process(img):
        if save_dir is not None:
            tar_path = save_image_as_tar(img, save_dir, tools, dry_run, insecure, ca_cert, username, password)
            print(f"[INFO] {img} -> {tar_path}")
            return tar_path

        new = rewrite_image(img, registry, prefix)
        if skip_existing and not dry_run and _image_exists(new, tools, insecure, ca_cert, username, password):
            print(f"[SKIP] {img} -> {new} (already exists)")
            return new
        print(f"[INFO] {img} -> {new}")
        if not dry_run:
            copy_image(img, new, tools, insecure, ca_cert, username, password)
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


def save_image_as_tar(image, output_dir, tools, dry_run=False, insecure=False, ca_cert=None, username=None, password=None):
    os.makedirs(output_dir, exist_ok=True)
    tar_path = os.path.join(output_dir, _image_to_filename(image))

    if dry_run:
        return tar_path

    if username or password:
        # Authentication is handled via temporary Docker config
        pass

    env = os.environ.copy()
    auth_temp_dir = None
    
    # Handle CA certificate
    if ca_cert and tools["copy"] in ("crane", "skopeo"):
        env["SSL_CERT_FILE"] = ca_cert
    elif ca_cert and tools["copy"] in ("docker", "podman"):
        print(
            f"[WARN] --ca-cert is not supported for {tools['copy']}. "
            "Configure the daemon's trust store for custom CAs."
        )
    
    # Handle authentication
    if username or password:
        # Determine registry for auth
        registry = _get_registry_from_image(image)
        auth_temp_dir, auth_env = _create_docker_auth_config(username, password, registry)
        if auth_temp_dir:
            env.update(auth_env)

    try:
        if tools["copy"] == "crane":
            cmd = ["crane", "pull"]
            if insecure:
                cmd.append("--insecure")
            subprocess.run(cmd + ["--format=tarball", image, tar_path], check=True, env=env)
        elif tools["copy"] == "skopeo":
            src = f"docker://{image}"
            dst = f"docker-archive:{tar_path}"
            cmd = ["skopeo", "copy"]
            if insecure:
                cmd += ["--src-tls-verify=false"]
            subprocess.run(cmd + [src, dst], check=True, env=env)
        elif tools["copy"] == "docker":
            if insecure:
                print(
                    "[WARN] --insecure has no effect for docker at the command level. "
                    "Add the registry to insecure-registries in /etc/docker/daemon.json."
                )
            subprocess.run(["docker", "pull", image], check=True)
            subprocess.run(["docker", "save", image, "-o", tar_path], check=True)
        else:
            tls = ["--tls-verify=false"] if insecure else []
            subprocess.run(["podman", "pull"] + tls + [image], check=True)
            subprocess.run(["podman", "save", image, "-o", tar_path], check=True)
    finally:
        # Clean up temporary auth directory
        if auth_temp_dir and os.path.exists(auth_temp_dir):
            import shutil
            shutil.rmtree(auth_temp_dir, ignore_errors=True)

    return tar_path


def copy_image(src, dst, tools, insecure=False, ca_cert=None, username=None, password=None):
    if username or password:
        # Authentication is handled via temporary Docker config
        pass

    env = os.environ.copy()
    auth_temp_dirs = []  # Track temp dirs for cleanup
    
    # Handle CA certificate
    if ca_cert and tools["copy"] in ("crane", "skopeo"):
        env["SSL_CERT_FILE"] = ca_cert
    elif ca_cert and tools["copy"] in ("docker", "podman"):
        print(
            f"[WARN] --ca-cert is not supported for {tools['copy']}. "
            "Configure the daemon's trust store for custom CAs."
        )
    
    # Handle authentication - need auth for both source and destination
    if username or password:
        # Create auth for source image
        src_registry = _get_registry_from_image(src)
        src_auth_temp_dir, src_auth_env = _create_docker_auth_config(username, password, src_registry)
        if src_auth_temp_dir:
            auth_temp_dirs.append(src_auth_temp_dir)
            env.update(src_auth_env)
        
        # Create auth for destination image (may be same credentials)
        dst_registry = _get_registry_from_image(dst)
        dst_auth_temp_dir, dst_auth_env = _create_docker_auth_config(username, password, dst_registry)
        if dst_auth_temp_dir:
            auth_temp_dirs.append(dst_auth_temp_dir)
            env.update(dst_auth_env)

    try:
        if tools["copy"] == "crane":
            cmd = ["crane", "copy"]
            if insecure:
                cmd.append("--insecure")
            subprocess.run(cmd + [src, dst], check=True, env=env)
        elif tools["copy"] == "skopeo":
            cmd = ["skopeo", "copy"]
            if insecure:
                cmd += ["--src-tls-verify=false", "--dest-tls-verify=false"]
            subprocess.run(cmd + [f"docker://{src}", f"docker://{dst}"], check=True, env=env)
        elif tools["copy"] == "docker":
            if insecure:
                print(
                    "[WARN] --insecure has no effect for docker at the command level. "
                    "Add the registry to insecure-registries in /etc/docker/daemon.json."
                )
            subprocess.run(["docker", "pull", src], check=True)
            subprocess.run(["docker", "tag", src, dst], check=True)
            subprocess.run(["docker", "push", dst], check=True)
        else:
            tls = ["--tls-verify=false"] if insecure else []
            subprocess.run(["podman", "pull"] + tls + [src], check=True)
            subprocess.run(["podman", "tag", src, dst], check=True)
            subprocess.run(["podman", "push"] + tls + [dst], check=True)
    finally:
        # Clean up temporary auth directories
        for auth_temp_dir in auth_temp_dirs:
            if auth_temp_dir and os.path.exists(auth_temp_dir):
                import shutil
                shutil.rmtree(auth_temp_dir, ignore_errors=True)


def write_image_list(images, path):
    with open(path, "w") as f:
        for img in images:
            f.write(img + "\n")
