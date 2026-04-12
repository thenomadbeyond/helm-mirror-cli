# helm-mirror-cli

A Python-based CLI tool designed to streamline the process of mirroring Helm charts and their associated container images to a private OCI registry. This is particularly useful for air-gapped environments or when you need to maintain a local cache of external dependencies.

## Features

- **Chart Pulling**: Automatically pulls and untars charts from remote repositories or local paths.
- **Image Discovery**: Renders Helm templates (with optional values files) to identify all container images used in the deployment.
- **Intelligent Extraction**: Uses `yq` for precise image extraction, with a robust regex-based fallback if `yq` is not installed.
- **Image Mirroring**: Copies images to a target registry using `crane`, `docker`, or `podman` (auto-detected).
- **Chart Mirroring**: Packages and pushes the Helm chart itself to a target OCI registry.
- **Dry Run Support**: Preview mirroring operations without executing actual network transfers.
- **Image Listing**: Generates a text file containing all mirrored image tags for auditing or post-processing.

## Prerequisites

The tool dynamically detects available system utilities. For consistent behavior, the following versions are recommended:

- **Python**: `^3.9.0`
- **Helm**: `^3.14.0`
- **yq**: `^4.40.0` (Recommended for robust YAML parsing)
- **Image Copy Tool**: `crane ^0.19.0` (preferred), `docker`, or `podman`.

## Usage

Run the tool as a Python module:

```bash
python3 -m src.main [OPTIONS]
```

### Arguments

| Argument | Description | Required |
| :--- | :--- | :--- |
| `--chart` | Helm chart name (e.g., `bitnami/nginx`) or local directory path. | Yes |
| `--target-registry` | The destination OCI registry (e.g., `my-registry.local`). | Yes |
| `--version` | Specific version of the Helm chart to pull. | No |
| `--values` | Path to a `values.yaml` file to use for rendering templates. | No |
| `--target-prefix` | Optional prefix to add to image paths (e.g., `mirrored-apps`). | No |
| `--push-chart` | If set, the packaged Helm chart will also be pushed to the registry. | No |
| `--chart-target` | Custom OCI URL for the chart push (defaults to `oci://<target-registry>`). | No |
| `--image-list-file` | Path to save a flat list of all mirrored image tags. | No |
| `--dry-run` | Logs planned operations without performing copies or pushes. | No |

## Example

Mirror the `devguard` chart and its images to a private registry with a specific prefix:

```bash
python3 -m src.main \
  --chart devguard \
  --version v1.1.0 \
  --values ./test/devguard/values.yaml \
  --target-registry registry.internal.corp \
  --target-prefix security-tools \
  --push-chart \
  --image-list-file output-images.txt
```

## How it Works

1. **Pull**: The tool pulls the specified Helm chart to a temporary directory.
2. **Render**: It runs `helm template` using the provided values to generate the full Kubernetes manifests.
3. **Extract**: It parses the manifests to find all `image:` keys using `yq` or regex.
4. **Rewrite**: It calculates the new image destination based on your `--target-registry` and `--target-prefix`.
5. **Copy**: It uses your local container tool (e.g., `crane copy`) to move the image directly from the source to the destination registry.
6. **Push (Optional)**: It packages the chart as a `.tgz` and pushes it to your OCI-compliant registry.

## License

This project is licensed under the Apache License 2.0. See LICENSE.md for details.

## Building a Standalone Binary

You can create a single executable for `helm-mirror-cli` using `PyInstaller`. This is useful for distributing the tool without requiring a Python environment on the target machine.

First, ensure `PyInstaller` is installed:

```bash
pip install pyinstaller
```

Then, build the binary:

```bash
pyinstaller --contents-directory src/ --name helm-mirror src/main.py
# The executable will be found in the 'dist/' directory.
./dist/helm-mirror --help
```

## Container Image

A Docker image is available for running `helm-mirror-cli` in containerized environments, such as Docker or Kubernetes. This image bundles all necessary dependencies, including `helm`, `yq`, and `crane`.

The official images are published to GitHub Container Registry (GHCR) at `ghcr.io/thenomadbeyond/helm-mirror-cli`.

To use the latest image:

```bash
docker run --rm \
  -v ~/.kube:/root/.kube:ro \
  -v ~/.config/helm:/root/.config/helm:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/thenomadbeyond/helm-mirror-cli:latest \
  --chart my-chart --target-registry my-registry.local ...
```

**Note**: When running in a container, ensure that the container has access to your Kubernetes configuration (`~/.kube`), Helm configuration (`~/.config/helm`), and potentially the Docker/Podman socket if you are using `docker` or `podman` as the image copy tool and need to interact with the host's daemon. For `crane`, direct registry access is usually sufficient.

### Building the Docker Image Locally

If you wish to build the Docker image yourself:

```bash
docker build -t helm-mirror-cli:local .
docker run --rm helm-mirror-cli:local --help
```