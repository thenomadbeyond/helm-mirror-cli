# mirror_tool/main.py
import argparse
import os
import sys
from helm import pull_chart, render_chart, push_chart, save_chart
from images import extract_images, filter_excluded, mirror_images, write_image_list
from runtime import detect_tools
from auth import registry_host


def main():
    parser = argparse.ArgumentParser(description="Helm + Image Mirror Tool")
    parser.add_argument("--chart", required=True)
    parser.add_argument("--version")
    parser.add_argument("--values")
    parser.add_argument("--target-registry")
    parser.add_argument("--target-prefix", default="")
    parser.add_argument("--push-chart", action="store_true")
    parser.add_argument("--chart-target")
    parser.add_argument("--image-list-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help=(
            "Allow insecure registries (HTTP or HTTPS with self-signed certs). "
            "For crane: passes --insecure. "
            "For skopeo: passes --src-tls-verify=false / --dest-tls-verify=false. "
            "For podman: passes --tls-verify=false. "
            "For helm: passes --insecure-skip-tls-verify. "
            "For docker: prints a warning — configure insecure-registries in /etc/docker/daemon.json instead."
        ),
    )
    parser.add_argument(
        "--ca-cert",
        help="Path to a custom CA certificate file to use for verifying registry certificates.",
    )
    parser.add_argument(
        "--username",
        help="Registry username (or set REGISTRY_USERNAME).",
    )
    parser.add_argument(
        "--password",
        help="Registry password. Visible in the process list and shell history; "
        "prefer --password-stdin or REGISTRY_PASSWORD.",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the registry password from the first line of stdin.",
    )
    parser.add_argument(
        "--auth-registry",
        metavar="HOST",
        help="Registry the credentials are valid for (default: host of --target-registry). "
        "Credentials are never sent to any other registry.",
    )
    parser.add_argument(
        "--repo-url",
        metavar="URL",
        help="Helm repository URL to add temporarily when --chart is just a chart name.",
    )
    parser.add_argument(
        "--save-images",
        action="store_true",
        help="Save images as local tar files instead of pushing to a registry.",
    )
    parser.add_argument(
        "--images-dir",
        default=".",
        metavar="DIR",
        help="Destination directory for saved image tar files (default: current directory). Only used with --save-images.",
    )
    parser.add_argument(
        "--save-chart",
        action="store_true",
        help="Save packaged chart as a local .tgz file instead of pushing to OCI.",
    )
    parser.add_argument(
        "--chart-dir",
        default=".",
        metavar="DIR",
        help="Destination directory for saved chart .tgz file (default: current directory). Only used with --save-chart.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Number of images to mirror concurrently (default: 1).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        metavar="N",
        help="Retry failed image copies N times with exponential backoff (default: 2).",
    )
    parser.add_argument(
        "--exclude-image",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Skip images matching this glob (repeatable), e.g. 'docker.io/bitnami/*'.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip images that already exist in the target registry (crane only).",
    )

    args = parser.parse_args()

    if not args.save_images and not args.target_registry:
        parser.error("--target-registry is required unless --save-images is used")

    username = args.username or os.environ.get("REGISTRY_USERNAME")
    password = os.environ.get("REGISTRY_PASSWORD")
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    elif args.password is not None:
        print("[WARN] --password is visible to other local users; prefer --password-stdin or REGISTRY_PASSWORD.")
        password = args.password
    if (username is None) != (password is None):
        parser.error("registry authentication needs both a username and a password")
    if args.parallel < 1 or args.retries < 0:
        parser.error("--parallel must be >= 1 and --retries >= 0")
    if args.ca_cert and not os.path.isfile(args.ca_cert):
        parser.error(f"--ca-cert file not found: {args.ca_cert}")

    auth = {"ca_cert": args.ca_cert}
    if password is not None:
        auth_registry = args.auth_registry or (
            registry_host(args.target_registry) if args.target_registry else None
        )
        if not auth_registry:
            parser.error("--auth-registry is required when using credentials with --save-images")
        auth.update(registry=auth_registry, username=username, password=password)

    tools = detect_tools()

    chart_path = pull_chart(args.chart, args.version, args.repo_url, args.insecure, args.ca_cert)
    rendered = render_chart(chart_path, args.values)

    images = filter_excluded(extract_images(rendered, tools), args.exclude_image)
    print(f"[INFO] Found {len(images)} images")

    mirrored = mirror_images(
        images,
        args.target_registry or "",
        args.target_prefix,
        tools,
        args.dry_run,
        save_dir=args.images_dir if args.save_images else None,
        insecure=args.insecure,
        auth=auth,
        parallel=args.parallel,
        skip_existing=args.skip_existing,
        retries=args.retries,
    )

    if args.image_list_file:
        write_image_list(mirrored, args.image_list_file)

    if args.save_chart:
        save_chart(chart_path, args.chart_dir)
    elif args.push_chart:
        push_chart(chart_path, args.target_registry, args.chart_target, args.insecure, auth)


if __name__ == "__main__":
    main()
