# Security Policy

## Supported Versions

| Version | Supported |
| :------ | :-------- |
| latest  | Yes       |

Older releases are not actively patched. Users are encouraged to always use the latest release.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/thenomadbeyond/helm-mirror-cli/security/advisories/new).

Include as much detail as possible:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Affected versions
- Any suggested mitigations

You can expect an acknowledgement within **5 business days** and a status update within **14 days**.

## Security Scanning

This project uses automated security scanning in CI/CD:

| Scan | Tool | Trigger | Results |
| :--- | :--- | :------- | :------ |
| Source code & dependencies | [Trivy](https://github.com/aquasecurity/trivy) | Every push to `main`, PRs | [GitHub Security tab](https://github.com/thenomadbeyond/helm-mirror-cli/security/code-scanning) |
| Docker image (build-time) | Trivy | Every push to `main` and version tags | GitHub Security tab |
| Binary (build-time) | Trivy | Every version tag | GitHub Security tab |
| Docker image (scheduled) | Trivy | Weekly (Monday 06:00 UTC) | GitHub Security tab |

Scan results for `CRITICAL` and `HIGH` severity findings are uploaded to the
[GitHub Security tab](https://github.com/thenomadbeyond/helm-mirror-cli/security/code-scanning)
as SARIF reports, where they can be reviewed and tracked.

## Supply Chain

- The Docker image is built on [`chainguard/wolfi-base`](https://github.com/chainguard-images/wolfi-base),
  a minimal, hardened base image with a low CVE surface area.
- The standalone Linux binary is built with [PyInstaller](https://pyinstaller.org/) on `ubuntu-latest`
  GitHub Actions runners and published directly as a GitHub Release asset.
- All CI/CD workflows use pinned action versions and rely only on `GITHUB_TOKEN`
  with least-privilege permissions — no external secrets are required.
