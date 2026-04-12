# mirror_tool/main.py
import argparse
from helm import pull_chart, render_chart, push_chart, save_chart
from images import extract_images, mirror_images, write_image_list
from runtime import detect_tools


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

    args = parser.parse_args()

    if not args.save_images and not args.target_registry:
        parser.error("--target-registry is required unless --save-images is used")

    tools = detect_tools()

    chart_path = pull_chart(args.chart, args.version)
    rendered = render_chart(chart_path, args.values)

    images = extract_images(rendered, tools)
    print(f"[INFO] Found {len(images)} images")

    mirrored = mirror_images(
        images,
        args.target_registry or "",
        args.target_prefix,
        tools,
        args.dry_run,
        save_dir=args.images_dir if args.save_images else None,
    )

    if args.image_list_file:
        write_image_list(mirrored, args.image_list_file)

    if args.save_chart:
        save_chart(chart_path, args.chart_dir)
    elif args.push_chart:
        push_chart(chart_path, args.target_registry, args.chart_target)


if __name__ == "__main__":
    main()
