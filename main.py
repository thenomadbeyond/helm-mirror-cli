# mirror_tool/main.py
import argparse
from helm import pull_chart, render_chart, push_chart
from images import extract_images, mirror_images, write_image_list
from runtime import detect_tools


def main():
    parser = argparse.ArgumentParser(description="Helm + Image Mirror Tool")
    parser.add_argument("--chart", required=True)
    parser.add_argument("--version")
    parser.add_argument("--values")
    parser.add_argument("--target-registry", required=True)
    parser.add_argument("--target-prefix", default="")
    parser.add_argument("--push-chart", action="store_true")
    parser.add_argument("--chart-target")
    parser.add_argument("--image-list-file")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    tools = detect_tools()

    chart_path = pull_chart(args.chart, args.version)
    rendered = render_chart(chart_path, args.values)

    images = extract_images(rendered, tools)
    print(f"[INFO] Found {len(images)} images")

    mirrored = mirror_images(images, args.target_registry, args.target_prefix, tools, args.dry_run)

    if args.image_list_file:
        write_image_list(mirrored, args.image_list_file)

    if args.push_chart:
        push_chart(chart_path, args.target_registry, args.chart_target)


if __name__ == "__main__":
    main()
