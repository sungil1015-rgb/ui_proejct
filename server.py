import base64
import binascii
import json
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from provided_algorithm import template_matching


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
DATA_DIR = Path("data")
TEMPLATE_ROOT_DIR = Path("templates")
OUTPUT_DIR = Path("outputs")

app = FastAPI(title="Parallel Image Similarity Inspector")


class InspectRequest(BaseModel):
    model_name: str = Field(..., min_length=1, description="Model folder name")
    product_id: str = Field(..., min_length=1, description="Product ID folder name")
    source_path: str = Field(
        ...,
        min_length=1,
        description="Original relative path, e.g. MODEL_A/PRODUCT_01/part_001.jpg",
    )
    image: str = Field(..., min_length=1, description="Base64 encoded image string")


class InspectionMaster:
    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        output_dir: Path = OUTPUT_DIR,
        template_root_dir: Path = TEMPLATE_ROOT_DIR,
        template_step_prefix: str = "step_tem_",
    ):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.template_root_dir = Path(template_root_dir)
        self.template_step_prefix = template_step_prefix

    def decode_base64_to_cv2_image(self, image_base64: str) -> np.ndarray:
        payload = image_base64.strip()
        if payload.startswith("data:") and "," in payload:
            payload = payload.split(",", 1)[1]

        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid Base64 image") from exc

        np_buffer = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(status_code=400, detail="Failed to decode image bytes")
        return image

    @staticmethod
    def _normalize_relative_path(path_text: str) -> Path:
        normalized = path_text.replace("\\", "/").strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="source_path is empty")

        path = Path(normalized)
        if path.is_absolute():
            raise HTTPException(status_code=400, detail="source_path must be relative")
        if any(part == ".." for part in path.parts):
            raise HTTPException(status_code=400, detail="source_path cannot contain '..'")
        if any(":" in part for part in path.parts):
            raise HTTPException(status_code=400, detail="source_path contains invalid drive info")

        clean_parts = [part for part in path.parts if part not in ("", ".")]
        if not clean_parts:
            raise HTTPException(status_code=400, detail="source_path is invalid")

        return Path(*clean_parts)

    @staticmethod
    def _extract_step_number(path: Path) -> int:
        match = re.search(r"step_(\d+)", path.stem.lower())
        if not match:
            raise HTTPException(
                status_code=400,
                detail="source_path filename must contain step_<number>",
            )
        return int(match.group(1))

    @staticmethod
    def _step_sort_key(path: Path):
        stem = path.stem.lower()
        if stem.startswith("step_"):
            try:
                return int(stem.split("_", 1)[1])
            except ValueError:
                return stem
        return stem

    def _collect_images(self, folder: Path):
        return sorted(
            [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS],
            key=self._step_sort_key,
        )

    @staticmethod
    def _read_image(path: Path) -> np.ndarray:
        image = cv2.imread(str(path))
        if image is None:
            raise FileNotFoundError(f"Failed to read image: {path}")
        return image

    def _find_reference_image_path(self, product_dir: Path, step_number: int) -> Path:
        run_images = self._collect_images(product_dir)
        if len(run_images) < 1:
            raise ValueError(f"No reference images found in: {product_dir}")

        target_stem = f"step_{step_number}"
        target_path = next((path for path in run_images if path.stem.lower() == target_stem), None)
        if target_path is None:
            raise FileNotFoundError(f"Reference image not found: {product_dir / target_stem}")
        return target_path

    def _template_step_names(self, step_number: int):
        names = [
            f"{self.template_step_prefix}{step_number:02d}",
            f"{self.template_step_prefix}{step_number}",
        ]
        return list(dict.fromkeys(names))

    def _load_manual_templates(self, model_name: str, product_id: str, step_number: int):
        template_base_dir = self.template_root_dir / model_name / product_id
        if not template_base_dir.exists() or not template_base_dir.is_dir():
            raise FileNotFoundError(f"Template base directory not found: {template_base_dir}")

        step_names = self._template_step_names(step_number)

        for step_name in step_names:
            template_dir = template_base_dir / step_name
            if template_dir.exists() and template_dir.is_dir():
                template_paths = self._collect_images(template_dir)
                if not template_paths:
                    raise ValueError(f"No template images found in: {template_dir}")
                return [self._read_image(path) for path in template_paths], str(template_dir)

        for step_name in step_names:
            template_paths = sorted(
                [
                    path
                    for path in template_base_dir.glob(f"{step_name}*")
                    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
                ]
            )
            if template_paths:
                return [self._read_image(path) for path in template_paths], str(template_base_dir)

        expected_paths = [str(template_base_dir / name) for name in step_names]
        raise FileNotFoundError(
            "Step template path not found. Expected one of: "
            + ", ".join(expected_paths)
            + " (folder or image files)"
        )

    def _build_output_image_path(self, payload: InspectRequest) -> Path:
        source_relative_path = self._normalize_relative_path(payload.source_path)

        if len(source_relative_path.parts) < 3:
            raise HTTPException(
                status_code=400,
                detail="source_path must include model_name/product_id/file_name",
            )

        if source_relative_path.parts[0] != payload.model_name or source_relative_path.parts[1] != payload.product_id:
            raise HTTPException(
                status_code=400,
                detail="source_path must start with model_name/product_id",
            )

        if source_relative_path.suffix.lower() not in IMAGE_EXTENSIONS:
            source_relative_path = source_relative_path.with_suffix(".jpg")

        return self.output_dir / source_relative_path

    def inspect(self, payload: InspectRequest) -> dict[str, Any]:
        input_img = self.decode_base64_to_cv2_image(payload.image)
        source_relative_path = self._normalize_relative_path(payload.source_path)
        step_number = self._extract_step_number(source_relative_path)

        product_dir = self.data_dir / payload.model_name / payload.product_id
        if not product_dir.exists() or not product_dir.is_dir():
            raise HTTPException(
                status_code=404,
                detail=f"Reference folder not found: {payload.model_name}/{payload.product_id}",
            )

        try:
            reference_image_path = self._find_reference_image_path(product_dir, step_number)
            template_all_img = self._read_image(reference_image_path)
            templates, template_source_path = self._load_manual_templates(
                payload.model_name,
                payload.product_id,
                step_number,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        output_image_path = self._build_output_image_path(payload)
        output_image_path.parent.mkdir(parents=True, exist_ok=True)

        _, scores, _ = template_matching(
            input_img=input_img,
            template_all=template_all_img,
            templates=templates,
            save_path=str(output_image_path.parent),
            output_filename=output_image_path.name,
        )

        avg_score = float(np.mean(scores)) if scores else 0.0
        metadata = {
            "model_name": payload.model_name,
            "product_id": payload.product_id,
            "source_path": payload.source_path,
            "step_number": step_number,
            "reference_image_path": str(reference_image_path),
            "template_source_path": template_source_path,
            "output_image_path": str(output_image_path),
            "scores": [float(score) for score in scores],
            "avg_score": avg_score,
        }

        metadata_path = output_image_path.with_suffix(".json")
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "model_name": payload.model_name,
            "product_id": payload.product_id,
            "source_path": payload.source_path,
            "step_number": step_number,
            "input_image_shape": list(input_img.shape),
            "scores": [float(score) for score in scores],
            "avg_score": avg_score,
            "reference_image_path": str(reference_image_path),
            "template_source_path": template_source_path,
            "result_image_path": str(output_image_path),
            "result_metadata_path": str(metadata_path),
        }


inspection_master = InspectionMaster()


@app.post("/inspect")
def inspect_endpoint(payload: InspectRequest):
    return inspection_master.inspect(payload)
