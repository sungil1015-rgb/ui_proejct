from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from statistics import mean
from typing import Any

import requests


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def _normalize_endpoint(server_url: str) -> str:
    base = server_url.rstrip("/")
    if base.endswith("/inspect"):
        return base
    return f"{base}/inspect"


def _collect_images(data_dir: Path) -> list[Path]:
    return sorted(
        [path for path in data_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    )


def _build_payload_from_data_root(image_path: Path, data_dir: Path) -> dict[str, str]:
    rel_path = image_path.resolve().relative_to(data_dir.resolve()).as_posix()
    parts = Path(rel_path).parts
    if len(parts) < 3:
        raise ValueError(
            "Image path under data root must be at least <model_name>/<product_id>/<image_file>: "
            f"{rel_path}"
        )

    image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

    return {
        "model_name": parts[0],
        "product_id": parts[1],
        "source_path": rel_path,
        "image": image_b64,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send all images in data folder to /inspect endpoint using Base64 JSON payload",
        epilog=(
            "Example:\n"
            "  python client.py --server-url http://127.0.0.1:8000 --data-dir C:/client_data/data\n"
            "  python client.py --server-url http://127.0.0.1:8000 --data-dir data --limit 10 --pretty"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--server-url", required=True, help="Server base URL or /inspect URL")
    parser.add_argument("--data-dir", default="data", help="Data root directory to scan recursively")
    parser.add_argument("--timeout", type=float, default=60.0, help="Request timeout seconds")
    parser.add_argument("--limit", type=int, default=0, help="Send only first N images (0 means all)")
    parser.add_argument("--report-path", default="client_send_report.json", help="Save send report as JSON")
    parser.add_argument("--pretty", action="store_true", help="Print full JSON response")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    endpoint = _normalize_endpoint(args.server_url)
    data_dir = Path(args.data_dir)

    if not data_dir.exists() or not data_dir.is_dir():
        print(f"[ERROR] data directory not found: {data_dir}")
        return

    images = _collect_images(data_dir)
    if args.limit > 0:
        images = images[: args.limit]

    if not images:
        print(f"[ERROR] no image files found under: {data_dir}")
        return

    print(f"[INFO] POST {endpoint}")
    print(f"[INFO] data_dir={data_dir.resolve()}")
    print(f"[INFO] image_count={len(images)}")

    successes: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    for index, image_path in enumerate(images, start=1):
        try:
            payload = _build_payload_from_data_root(image_path=image_path, data_dir=data_dir)
        except Exception as exc:  # noqa: BLE001
            failures.append({"image_path": str(image_path), "stage": "payload", "error": str(exc)})
            print(f"[{index}/{len(images)}] [FAIL] payload: {image_path} -> {exc}")
            continue

        print(
            f"[{index}/{len(images)}] [SEND] "
            f"model={payload['model_name']} product={payload['product_id']} source={payload['source_path']}"
        )

        try:
            response = requests.post(endpoint, json=payload, timeout=args.timeout)
        except requests.RequestException as exc:
            failures.append({
                "image_path": str(image_path),
                "source_path": payload["source_path"],
                "stage": "request",
                "error": str(exc),
            })
            print(f"[{index}/{len(images)}] [FAIL] request: {exc}")
            continue

        if response.status_code != 200:
            failures.append(
                {
                    "image_path": str(image_path),
                    "source_path": payload["source_path"],
                    "stage": "response",
                    "status_code": response.status_code,
                    "error": response.text,
                }
            )
            print(f"[{index}/{len(images)}] [FAIL] status={response.status_code}")
            continue

        try:
            result = response.json()
        except ValueError:
            failures.append(
                {
                    "image_path": str(image_path),
                    "source_path": payload["source_path"],
                    "stage": "response-json",
                    "error": "response is not valid JSON",
                    "raw": response.text,
                }
            )
            print(f"[{index}/{len(images)}] [FAIL] invalid JSON response")
            continue

        avg_score = _as_float(result.get("avg_score"), 0.0)
        successes.append(
            {
                "image_path": str(image_path),
                "source_path": payload["source_path"],
                "avg_score": avg_score,
                "result_image_path": result.get("result_image_path"),
                "result_metadata_path": result.get("result_metadata_path"),
                "response": result,
            }
        )
        print(
            f"[{index}/{len(images)}] [OK] avg_score={avg_score:.6f} "
            f"result={result.get('result_image_path')}"
        )
        if args.pretty:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    report = {
        "server_endpoint": endpoint,
        "data_dir": str(data_dir.resolve()),
        "total": len(images),
        "success": len(successes),
        "failed": len(failures),
        "mean_avg_score": mean([item["avg_score"] for item in successes]) if successes else 0.0,
        "successes": successes,
        "failures": failures,
    }

    report_path = Path(args.report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Summary ===")
    print(f"total={report['total']}, success={report['success']}, failed={report['failed']}")
    print(f"mean_avg_score={report['mean_avg_score']:.6f}")
    print(f"report_path={report_path.resolve()}")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    main()