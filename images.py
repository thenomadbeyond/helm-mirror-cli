
# mirror_tool/images.py
import subprocess
import re


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


def mirror_images(images, registry, prefix, tools, dry_run=False):
    mirrored = []

    for img in images:
        new = rewrite_image(img, registry, prefix)
        print(f"[INFO] {img} -> {new}")

        if not dry_run:
            copy_image(img, new, tools)

        mirrored.append(new)

    return mirrored


def rewrite_image(image, registry, prefix):
    parts = image.split("/")

    if len(parts) > 1 and "." in parts[0]:
        parts = parts[1:]

    new = "/".join(parts)

    if prefix:
        new = f"{prefix}/{new}"

    return f"{registry}/{new}"


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


