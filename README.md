# helm-mirror-cli

[![Build and Publish Docker Image](https://github.com/thenomadbeyond/helm-mirror-cli/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/thenomadbeyond/helm-mirror-cli/actions/workflows/docker-publish.yml)
[![Build Linux Binary](https://github.com/thenomadbeyond/helm-mirror-cli/actions/workflows/binary-build.yml/badge.svg)](https://github.com/thenomadbeyond/helm-mirror-cli/actions/workflows/binary-build.yml)
[![Security Scan](https://github.com/thenomadbeyond/helm-mirror-cli/actions/workflows/security-scan.yml/badge.svg)](https://github.com/thenomadbeyond/helm-mirror-cli/actions/workflows/security-scan.yml)

A CLI tool for mirroring Helm charts and their container images to a private OCI registry.
Designed for air-gapped environments or maintaining a local cache of external dependencies.

## Features

- **Chart Pulling** — pulls and untars charts from remote repositories or local paths
- **Image Discovery** — renders Helm templates to identify all container images
- **Intelligent Extraction** — uses `yq` for precise extraction with a regex fallback
- **Image Mirroring** — copies images via `crane`, `skopeo`, `docker`, or `podman` (auto-detected; `skopeo` preferred over `docker`/`podman`)
- **Local Save Mode** — save images as tar files or charts as `.tgz` without pushing to a registry
- **Chart Mirroring** — packages and pushes the Helm chart to a target OCI registry
- **Dry Run** — preview operations without executing network transfers
- **Image Listing** — writes all mirrored image tags to a file for auditing

## Prerequisites

| Tool | Version | Notes |
| :--- | :------ | :---- |
| Python | `^3.9` | Only needed when running from source |
| Helm | `^3.14` | Required |
| yq | `^4.40` | Recommended — falls back to regex without it |
| crane | `^0.19` | Preferred copy tool |
| skopeo | `^1.13` | Second choice — daemonless, no container runtime required |
| docker / podman | any | Fallback copy tools (require running daemon)

## Installation

### Standalone Binary (recommended)

Download the latest pre-built Linux binary from the [Releases page](https://github.com/thenomadbeyond/helm-mirror-cli/releases) and install it:

```bash
sudo install -m 755 helm-mirror /usr/local/bin/helm-mirror
helm-mirror --help
```

### Docker Image

```bash
docker pull ghcr.io/thenomadbeyond/helm-mirror-cli:latest
```

### From Source

```bash
git clone https://github.com/thenomadbeyond/helm-mirror-cli.git
cd helm-mirror-cli
pip install -r requirements.txt
python3 src/main.py --help
```

## Usage

```
helm-mirror --chart CHART [OPTIONS]
```

### Arguments

| Argument | Description | Required |
| :--- | :--- | :--- |
| `--chart` | Chart name (e.g. `bitnami/nginx`) or local directory path | Yes |
| `--target-registry` | Destination OCI registry (e.g. `my-registry.local`) | Unless `--save-images` |
| `--version` | Specific chart version to pull | No |
| `--values` | Path to a `values.yaml` for template rendering | No |
| `--target-prefix` | Prefix added to image paths in the target registry | No |
| `--push-chart` | Push the packaged chart to the target OCI registry | No |
| `--chart-target` | Custom OCI URL for chart push (default: `oci://<target-registry>`) | No |
| `--image-list-file` | Write all mirrored image tags to this file | No |
| `--dry-run` | Log planned operations without executing them | No |
| `--save-images` | Save images as local tar files instead of pushing to a registry | No |
| `--images-dir DIR` | Output directory for image tar files (default: `.`) — requires `--save-images` | No |
| `--save-chart` | Save the packaged chart as a local `.tgz` instead of pushing | No |
| `--chart-dir DIR` | Output directory for the chart `.tgz` (default: `.`) — requires `--save-chart` | No |

### Examples

**Mirror to a private registry:**

```bash
helm-mirror \
  --chart bitnami/nginx \
  --version 18.1.0 \
  --target-registry registry.internal.corp \
  --target-prefix mirrored \
  --push-chart \
  --image-list-file mirrored-images.txt
```

**Save images and chart locally (air-gapped preparation):**

```bash
helm-mirror \
  --chart bitnami/nginx \
  --save-images --images-dir ./output/images \
  --save-chart --chart-dir ./output/charts
```

**Dry run to preview what would be mirrored:**

```bash
helm-mirror \
  --chart bitnami/nginx \
  --target-registry registry.internal.corp \
  --dry-run
```

**Run via Docker:**

```bash
docker run --rm \
  -v ~/.config/helm:/root/.config/helm:ro \
  ghcr.io/thenomadbeyond/helm-mirror-cli:latest \
  --chart bitnami/nginx \
  --target-registry registry.internal.corp \
  --push-chart
```

## Docker Usage with Volume Mounts

When running the Docker image, you may need to mount volumes for:
- Local charts (if using `--chart` with a local path)
- Output directories (for `--save-images`/`--images-dir` and `--save-chart`/`--chart-dir`)
- Temporary storage (if the default `/tmp` is not writable or you want to persist temporary files)

The image runs as a nonroot user (UID 1000). Ensure that any mounted directories are writable by this user.

### Example: Using Local Charts and Saving Output

```bash
docker run --rm \
  -v ~/.config/helm:/root/.config/helm:ro \
  -v $(pwd)/local-charts:/charts:ro \
  -v $(pwd)/output:/output:rw \
  -v $(pwd)/tmp:/tmp:rw \
  ghcr.io/thenomadbeyond/helm-mirror-cli:latest \
  --chart /charts/my-chart \
  --save-images --images-dir /output/images \
  --save-chart --chart-dir /output/charts \
  --target-registry my-registry.example.com \
  --push-chart
```

### Explanation:
- `-v $(pwd)/local-charts:/charts:ro`: Mount local charts directory as read-only at `/charts`
- `-v $(pwd)/output:/output:rw`: Mount output directory as read-write at `/output`
- `-v $(pwd)/tmp:/tmp:rw`: Mount temporary directory as read-write at `/tmp` (overrides the container's tmp)
- The chart is then referenced as `/charts/my-chart`
- Output directories are under `/output`
- Temporary files (used for extracting charts, etc.) will be stored in `/tmp` on the host

### Alternative: Setting TMPDIR Environment Variable

If you prefer not to mount `/tmp`, you can set the `TMPDIR` environment variable to a writable mounted directory:

```bash
docker run --rm \
  -v ~/.config/helm:/root/.config/helm:ro \
  -v $(pwd)/local-charts:/charts:ro \
  -v $(pwd)/output:/output:rw \
  -v $(pwd)/tmp:/tmp:rw \
  -e TMPDIR=/tmp \
  ghcr.io/thenomadbeyond/helm-mirror-cli:latest \
  --chart /charts/my-chart \
  --save-images --images-dir /output/images \
  --save-chart --chart-dir /output/charts \
  --target-registry my-registry.example.com \
  --push-chart
```

Note: The image already uses `/tmp` as the default temporary directory, so mounting a host directory to `/tmp` is often sufficient.

### Important Notes
- The nonroot user in the container has UID 1000. If you get permission errors, ensure the host directories are writable by UID 1000 (e.g., `chmod a+rw` or change ownership to 1000:1000).
- For reading local charts, the mount can be read-only (`:ro`).
- For writing output or temporary files, the mount must be read-write (`:rw`).
## CI/CD Pipelines

| Workflow | Trigger | Description |
| :------- | :------ | :---------- |
| `docker-publish.yml` | Push to `main`, version tags, PRs | Builds and pushes Docker image to GHCR; scans image with Trivy |
| `binary-build.yml` | Version tags, manual | Builds Linux binary with PyInstaller; scans binary with Trivy; publishes GitHub Release |
| `security-scan.yml` | Weekly (Mon 06:00 UTC), push to `main`, PRs | Scans source code and published Docker image with Trivy |

Security findings are uploaded as SARIF reports to the [GitHub Security tab](https://github.com/thenomadbeyond/helm-mirror-cli/security/code-scanning).

## Building Locally

**Binary:**

```bash
pip install pyinstaller
pyinstaller --onefile -n helm-mirror src/main.py
# output: dist/helm-mirror
```

**Docker image:**

```bash
docker build -t helm-mirror-cli:local .
docker run --rm helm-mirror-cli:local --help
```

## Security

See [SECURITY.md](SECURITY.md) for the vulnerability reporting policy and details on automated security scanning.

The latest Docker image is automatically rebuilt every six hours to incorporate the latest security patches from the base image and dependencies.

## License

Apache License 2.0. See LICENSE for details.
