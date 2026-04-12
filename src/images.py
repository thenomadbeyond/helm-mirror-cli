# mirror_tool/images.py
import subprocess
import re
import os


def extract_images(rendered_yaml, tools):
    images = set()

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

    pattern = re.compile(r"image:\s*([^\s]+)")
    for line in rendered_yaml.splitlines():
        m = pattern.search(line)
        if m:
            images.add(m.group(1))

    return images


def mirror_images(images, registry, prefix, tools, dry_run=False, save_dir=None):
    mirrored = []

    for img in images:
        if save_dir is not None:
            tar_path = save_image_as_tar(img, save_dir, tools, dry_run)
            print(f"[INFO] {img} -> {tar_path}")
            mirrored.append((img, tar_path))
        else:
            new = rewrite_image(img, registry, prefix)
            print(f"[INFO] {img} -> {new}")
            if not dry_run:
                copy_image(img, new, tools)
            mirrored.append((img, new))

    print("\n[INFO] Mirrored images summary:")
    for src, dst in mirrored:
        print(f"  {src} -> {dst}")

    return [dst for _, dst in mirrored]


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


def save_image_as_tar(image, output_dir, tools, dry_run=False):
    os.makedirs(output_dir, exist_ok=True)
    tar_path = os.path.join(output_dir, _image_to_filename(image))

    if dry_run:
        return tar_path

    if tools["copy"] == "crane":
        subprocess.run(["crane", "pull", "--format=tarball", image, tar_path], check=True)
    elif tools["copy"] == "docker":
        subprocess.run(["docker", "pull", image], check=True)
        subprocess.run(["docker", "save", image, "-o", tar_path], check=True)
    else:
        subprocess.run(["podman", "pull", image], check=True)
        subprocess.run(["podman", "save", image, "-o", tar_path], check=True)

    return tar_path


def copy_image(src, dst, tools):
    if tools["copy"] == "crane":
        subprocess.run(["crane", "copy", src, dst], check=True)
    elif tools["copy"] == "docker":
        subprocess.run(["docker", "pull", src], check=True)
        subprocess.run(["docker", "tag", src, dst], check=True)
        subprocess.run(["docker", "push", dst], check=True)
    else:
        subprocess.run(["podman", "pull", src], check=True)
        subprocess.run(["podman", "tag", src, dst], check=True)
        subprocess.run(["podman", "push", dst], check=True)


def write_image_list(images, path):
    with open(path, "w") as f:
        for img in images:
            f.write(img + "\n")


