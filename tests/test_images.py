import subprocess

import pytest

import images


def extract(doc):
    return images.extract_images(doc, {})


def test_standard_image_string():
    assert extract("image: nginx:1.27") == {"nginx:1.27"}


def test_nested_repository_and_numeric_tag_is_not_mangled():
    doc = "image:\n  repository: quay.io/foo/bar\n  tag: 1.10\n"
    assert extract(doc) == {"quay.io/foo/bar:1.10"}


def test_sibling_repository_image_version():
    doc = "repository: nvcr.io/nvidia\nimage: gpu-operator\nversion: v1.2\n"
    assert extract(doc) == {"nvcr.io/nvidia/gpu-operator:v1.2"}


@pytest.mark.parametrize("bad", ["--insecure", "-x", "a b", "img;rm", "$(id)"])
def test_invalid_refs_are_dropped(bad):
    assert extract(f"image: '{bad}'") == set()


def test_exclude_patterns():
    imgs = {"docker.io/bitnami/nginx:1", "quay.io/a/b:2"}
    assert images.filter_excluded(imgs, ["docker.io/bitnami/*"]) == {"quay.io/a/b:2"}


@pytest.mark.parametrize(
    "image,expected",
    [
        ("docker.io/library/nginx:1", "reg.io/mirror/library/nginx:1"),
        ("nginx:1", "reg.io/mirror/nginx:1"),
        ("quay.io/a/b@sha256:abc", "reg.io/mirror/a/b@sha256:abc"),
    ],
)
def test_rewrite_image(image, expected):
    assert images.rewrite_image(image, "reg.io", "mirror") == expected


def test_tar_filename_has_no_path_separators():
    assert "/" not in images._image_to_filename("a/b/../c:1")


def test_run_retry_retries_then_succeeds(monkeypatch):
    calls = []

    def fake_run(cmd, check, env):
        calls.append(cmd)
        if len(calls) < 3:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(images.subprocess, "run", fake_run)
    monkeypatch.setattr(images.time, "sleep", lambda s: None)
    images._run_retry(["crane", "copy", "a", "b"], {}, retries=2)
    assert len(calls) == 3


def test_run_retry_gives_up(monkeypatch):
    def fake_run(cmd, check, env):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(images.subprocess, "run", fake_run)
    monkeypatch.setattr(images.time, "sleep", lambda s: None)
    with pytest.raises(subprocess.CalledProcessError):
        images._run_retry(["crane", "copy", "a", "b"], {}, retries=1)


def test_mirror_images_reports_failures_but_attempts_all(monkeypatch):
    seen = []

    def fake_copy(src, dst, tools, insecure, auth, retries):
        seen.append(src)
        if src == "bad:1":
            raise RuntimeError("boom")

    monkeypatch.setattr(images, "copy_image", fake_copy)
    with pytest.raises(RuntimeError, match="1 image"):
        images.mirror_images(["ok:1", "bad:1", "ok:2"], "r.io", "", {"copy": "crane"})
    assert sorted(seen) == ["bad:1", "ok:1", "ok:2"]
