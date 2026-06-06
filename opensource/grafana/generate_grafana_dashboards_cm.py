from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_configmap(dashboards_dir: Path, configmap_name: str, namespace: str) -> str:
    dashboard_files = sorted(dashboards_dir.glob("*.json"))
    if not dashboard_files:
        raise SystemExit(f"No dashboard JSON files found in {dashboards_dir}")

    lines: list[str] = [
        "apiVersion: v1",
        "kind: ConfigMap",
        "metadata:",
        f"  name: {configmap_name}",
        f"  namespace: {namespace}",
        "  labels:",
        "    app: grafana",
        "    component: dashboards",
        "data:",
    ]

    for dashboard_file in dashboard_files:
        content = dashboard_file.read_text(encoding="utf-8").rstrip("\n")
        lines.append(f"  {dashboard_file.name}: |")
        for content_line in content.splitlines():
            lines.append(f"    {content_line}")

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and apply a Grafana dashboards ConfigMap from JSON files in dashboards/."
    )
    parser.add_argument(
        "--dashboards-dir",
        default=Path(__file__).with_name("dashboards"),
        type=Path,
        help="Directory containing dashboard JSON files.",
    )
    parser.add_argument(
        "--name",
        default="grafana-dashboards-myrca",
        help="ConfigMap name.",
    )
    parser.add_argument(
        "--namespace",
        default="grafana",
        help="Kubernetes namespace for the ConfigMap.",
    )
    parser.add_argument(
        "--kubectl",
        default="kubectl",
        help="Kubectl executable to use when applying the ConfigMap.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configmap_text = build_configmap(args.dashboards_dir, args.name, args.namespace)
    process = subprocess.run(
        [args.kubectl, "apply", "-f", "-"],
        input=configmap_text.encode("utf-8"),
        capture_output=True,
        check=False,
    )

    if process.returncode != 0:
        if process.stdout:
            sys.stdout.buffer.write(process.stdout)
        if process.stderr:
            sys.stderr.buffer.write(process.stderr)
        raise SystemExit(process.returncode)

    if process.stdout:
        sys.stdout.buffer.write(process.stdout)


if __name__ == "__main__":
    main()