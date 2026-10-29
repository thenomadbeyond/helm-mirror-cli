import json
import os

import pytest

from auth import registry_env, registry_host


def test_registry_host():
    assert registry_host("reg.example.com:5000/prefix") == "reg.example.com:5000"
    assert registry_host("https://reg.example.com") == "reg.example.com"


def test_credentials_only_for_target_and_private():
    with registry_env("crane", "reg.example.com", "u", "p") as env:
        cfg = os.path.join(env["DOCKER_CONFIG"], "config.json")
        assert oct(os.stat(cfg).st_mode & 0o777) == "0o600"
        assert list(json.load(open(cfg))["auths"]) == ["reg.example.com"]
        tmp = env["DOCKER_CONFIG"]
    assert not os.path.exists(tmp)


def test_docker_hub_key():
    with registry_env("crane", "docker.io", "u", "p") as env:
        auths = json.load(open(env["REGISTRY_AUTH_FILE"]))["auths"]
        assert list(auths) == ["https://index.docker.io/v1/"]


def test_password_requires_username_and_registry():
    with pytest.raises(ValueError):
        with registry_env("crane", "reg", None, "p"):
            pass


def test_ca_cert_is_appended_not_replacing(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\nCUSTOM\n-----END CERTIFICATE-----\n")
    with registry_env("skopeo", ca_cert=str(ca)) as env:
        assert "CUSTOM" in open(env["SSL_CERT_FILE"]).read()


def test_no_credentials_leaves_env_untouched():
    with registry_env("crane") as env:
        assert env.get("DOCKER_CONFIG") == os.environ.get("DOCKER_CONFIG")
