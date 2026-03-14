from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

import streamlit as st


OUTPUT_DIR = Path("outputs")


def _as_float(value: Any, default: float = 0.0) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _as_int(value: Any) -> int | None:
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _to_abs_path(path_text: Any, root_dir: Path) -> Path | None:
	if not path_text:
		return None
	path = Path(str(path_text).replace("\\", "/"))
	if path.is_absolute():
		return path
	return root_dir / path


@st.cache_data(show_spinner=False)
def load_json_records(outputs_dir_text: str, root_dir_text: str):
	root_dir = Path(root_dir_text)
	outputs_dir = Path(outputs_dir_text)
	if not outputs_dir.is_absolute():
		outputs_dir = root_dir / outputs_dir

	records = []
	errors = []

	if not outputs_dir.exists():
		errors.append({"path": str(outputs_dir), "error": "outputs directory not found"})
		return records, errors

	for json_path in sorted(outputs_dir.rglob("*.json")):
		try:
			data = json.loads(json_path.read_text(encoding="utf-8"))
			if not isinstance(data, dict):
				raise ValueError("JSON root must be an object")
		except Exception as exc:  # noqa: BLE001
			errors.append({"path": str(json_path), "error": str(exc)})
			continue

		row = dict(data)
		row["_json_path"] = str(json_path)
		row["_model"] = str(row.get("model_name", ""))
		row["_product"] = str(row.get("product_id", ""))
		row["_step"] = _as_int(row.get("step_number"))
		row["_avg_score"] = _as_float(row.get("avg_score"), 0.0)

		scores = row.get("scores", [])
		if isinstance(scores, list):
			row["scores"] = [_as_float(score, 0.0) for score in scores]
		else:
			row["scores"] = []

		records.append(row)

	return records, errors


def _render_summary(records: list[dict[str, Any]], filtered: list[dict[str, Any]], errors: list[dict[str, str]]):
	col1, col2, col3, col4 = st.columns(4)
	col1.metric("Total JSON", len(records))
	col2.metric("Filtered", len(filtered))
	col3.metric("Load Errors", len(errors))

	if records:
		col4.metric("Mean avg_score", f"{mean([item['_avg_score'] for item in records]):.6f}")
	else:
		col4.metric("Mean avg_score", "0.000000")


def _render_table(filtered: list[dict[str, Any]]):
	rows = [
		{
			"model_name": row.get("model_name"),
			"product_id": row.get("product_id"),
			"step_number": row.get("step_number"),
			"avg_score": round(row.get("_avg_score", 0.0), 6),
			"source_path": row.get("source_path"),
			"json_path": row.get("_json_path"),
		}
		for row in filtered
	]
	st.dataframe(rows, use_container_width=True, hide_index=True)


def _record_label(row: dict[str, Any]) -> str:
	model = row.get("model_name", "-")
	product = row.get("product_id", "-")
	step = row.get("step_number", "-")
	avg = row.get("_avg_score", 0.0)
	src = row.get("source_path", "-")
	return f"{model}/{product} | step={step} | avg={avg:.6f} | {src}"


def main():
	st.set_page_config(page_title="Inspection JSON Viewer", layout="wide")
	st.title("Inspection JSON Viewer")
	st.caption("outputs 폴더의 JSON 결과를 필터링하고 상세 내용을 확인합니다.")

	root_dir = Path(__file__).resolve().parent

	with st.sidebar:
		st.header("Filter")
		outputs_dir_text = st.text_input("Outputs Path", value=str(OUTPUT_DIR))
		if st.button("Refresh"):
			load_json_records.clear()
			st.rerun()

	records, errors = load_json_records(outputs_dir_text, str(root_dir))
	if not records:
		st.warning("표시할 JSON 데이터가 없습니다.")
		if errors:
			st.dataframe(errors, use_container_width=True, hide_index=True)
		return

	models = sorted({row["_model"] for row in records if row["_model"]})
	selected_model = st.sidebar.selectbox("Model", ["(All)"] + models)

	model_filtered = [
		row for row in records if selected_model == "(All)" or row["_model"] == selected_model
	]
	products = sorted({row["_product"] for row in model_filtered if row["_product"]})
	selected_product = st.sidebar.selectbox("Product", ["(All)"] + products)

	product_filtered = [
		row for row in model_filtered if selected_product == "(All)" or row["_product"] == selected_product
	]
	steps = sorted({row["_step"] for row in product_filtered if row["_step"] is not None})
	selected_steps = st.sidebar.multiselect("Step", options=steps, default=[])

	min_avg_score = st.sidebar.slider("Min avg_score", 0.0, 1.0, 0.0, 0.001)
	keyword = st.sidebar.text_input("Keyword (source_path)").strip().lower()

	filtered = []
	for row in product_filtered:
		if selected_steps and row["_step"] not in selected_steps:
			continue
		if row["_avg_score"] < min_avg_score:
			continue
		if keyword and keyword not in str(row.get("source_path", "")).lower():
			continue
		filtered.append(row)

	_render_summary(records, filtered, errors)

	st.subheader("Result Table")
	_render_table(filtered)

	if not filtered:
		st.info("필터 조건에 맞는 JSON이 없습니다.")
		return

	st.subheader("Detail")
	selected_index = st.selectbox(
		"Select Record",
		options=list(range(len(filtered))),
		format_func=lambda i: _record_label(filtered[i]),
	)
	selected = filtered[selected_index]

	left_col, right_col = st.columns(2)
	with left_col:
		st.markdown("**JSON Data**")
		st.json(selected, expanded=False)

	with right_col:
		st.markdown("**Scores**")
		if selected.get("scores"):
			st.line_chart(selected["scores"])
		else:
			st.info("scores 값이 없습니다.")

	img_col1, img_col2 = st.columns(2)
	output_img_path = _to_abs_path(selected.get("output_image_path"), root_dir)
	ref_img_path = _to_abs_path(selected.get("reference_image_path"), root_dir)

	with img_col1:
		st.markdown("**Output Image**")
		if output_img_path and output_img_path.exists():
			st.image(str(output_img_path), use_container_width=True)
			st.code(str(output_img_path))
		else:
			st.warning(f"이미지를 찾을 수 없습니다: {output_img_path}")

	with img_col2:
		st.markdown("**Reference Image**")
		if ref_img_path and ref_img_path.exists():
			st.image(str(ref_img_path), use_container_width=True)
			st.code(str(ref_img_path))
		else:
			st.warning(f"이미지를 찾을 수 없습니다: {ref_img_path}")

	if errors:
		with st.expander("Load Errors"):
			st.dataframe(errors, use_container_width=True, hide_index=True)


if __name__ == "__main__":
	main()
