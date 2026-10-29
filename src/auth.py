# mirror_tool/auth.py
import contextlib
import json
import os
import shutil
import ssl
import tempfile
from base64 import b64encode

_DOCKER_HUB = "https://index.docker.io/v1/"
_HUB_HOSTS = {"docker.io", "index.docker.io", "registry-1.docker.io"}
_SYSTEM_CA_FALLBACKS = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)


def registry_host(target):
    """Host[:port] of a target registry string such as host:5000/prefix."""
    return target.split("://", 1)[-1].split("/", 1)[0]


def _system_ca_bundle():
    for path in (ssl.get_default_verify_paths().cafile, *_SYSTEM_CA_FALLBACKS):
        if path and os.path.isfile(path):
            return path
    return None


def _write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


@contextlib.contextmanager
def registry_env(tool, registry=None, username=None, password=None, ca_cert=None):
    """Yield a subprocess environment carrying registry credentials / a CA.

    Credentials are written to a private temp config that only contains an
    entry for `registry`, so they are never offered to any other host (e.g.
    the upstream source registry). The temp dir is always removed on exit.
    """
    env = os.environ.copy()
    tmp = tempfile.mkdtemp(prefix="helm-mirror-")
    try:
        if password is not None:
            if not (username and registry):
                raise ValueError("credentials need both a username and a registry")
            key = _DOCKER_HUB if registry in _HUB_HOSTS else registry
            auth = b64encode(f"{username}:{password}".encode()).decode()
            cfg = os.path.join(tmp, "config.json")
            _write_private(cfg, json.dumps({"auths": {key: {"auth": auth}}}))
            # docker/crane/skopeo read DOCKER_CONFIG, podman/skopeo read
            # REGISTRY_AUTH_FILE, helm reads HELM_REGISTRY_CONFIG.
            env["DOCKER_CONFIG"] = tmp
            env["REGISTRY_AUTH_FILE"] = cfg
            env["HELM_REGISTRY_CONFIG"] = cfg

        if ca_cert:
            if tool in ("docker", "podman"):
                print(
                    f"[WARN] --ca-cert is not supported for {tool}. "
                    "Configure the daemon's trust store for custom CAs."
                )
            else:
                # SSL_CERT_FILE replaces the trust store, so append the custom CA
                # to the system bundle instead of losing public registries.
                bundle = os.path.join(tmp, "ca-bundle.pem")
                parts = []
                system = _system_ca_bundle()
                if system:
                    with open(system) as f:
                        parts.append(f.read())
                with open(ca_cert) as f:
                    parts.append(f.read())
                _write_private(bundle, "\n".join(parts))
                env["SSL_CERT_FILE"] = bundle

        yield env
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
