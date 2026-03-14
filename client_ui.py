from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any

import streamlit as st


DEFAULT_REPORT_PATH = Path("client_send_report.json")
STEP_PATTERN = re.compile(r"step[_-]?(\d+)", re.IGNORECASE)


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


def _path_part(source_path: Any, index: int) -> str:
	parts = Path(str(source_path).replace("\\", "/")).parts
	if len(parts) <= index:
		return ""
	return str(parts[index])


def _extract_step_number(source_path: Any) -> int | None:
	if not source_path:
		return None

	match = STEP_PATTERN.search(str(source_path))
	if not match:
		return None

	return _as_int(match.group(1))


def _to_abs_path(path_text: Any, root_dir: Path) -> Path | None:
	if not path_text:
		return None

	path = Path(str(path_text).replace("\\", "/"))
	if path.is_absolute():
		return path

	return root_dir / path


def _run_client_sender(
	root_dir: Path,
	server_url: str,
	data_dir: str,
	timeout_sec: float,
	limit: int,
	report_path: str,
	pretty: bool,
) -> dict[str, Any]:
	client_script = root_dir / "client.py"
	if not client_script.exists():
		raise FileNotFoundError(f"client.py not found: {client_script}")

	command = [
		sys.executable,
		str(client_script),
		"--server-url",
		server_url,
		"--data-dir",
		data_dir,
		"--timeout",
		str(timeout_sec),
		"--report-path",
		report_path,
	]

	if limit > 0:
		command.extend(["--limit", str(limit)])

	if pretty:
		command.append("--pretty")

	result = subprocess.run(
		command,
		cwd=str(root_dir),
		capture_output=True,
		text=True,
	)

	return {
		"command": subprocess.list2cmdline(command),
		"returncode": result.returncode,
		"stdout": result.stdout,
		"stderr": result.stderr,
	}


@st.cache_data(show_spinner=False)
def load_client_report(report_path_text: str, root_dir_text: str):
	root_dir = Path(root_dir_text)
	report_path = Path(report_path_text)
	if not report_path.is_absolute():
		report_path = root_dir / report_path

	errors: list[dict[str, str]] = []

	if not report_path.exists():
		errors.append({"path": str(report_path), "error": "report file not found"})
		return [], [], {}, errors

	try:
		report = json.loads(report_path.read_text(encoding="utf-8"))
		if not isinstance(report, dict):
			raise ValueError("Report JSON root must be an object")
	except Exception as exc:  # noqa: BLE001
		errors.append({"path": str(report_path), "error": str(exc)})
		return [], [], {}, errors

	raw_successes = report.get("successes", [])
	raw_failures = report.get("failures", [])

	if not isinstance(raw_successes, list):
		errors.append({"path": str(report_path), "error": "'successes' must be a list"})
		raw_successes = []

	if not isinstance(raw_failures, list):
		errors.append({"path": str(report_path), "error": "'failures' must be a list"})
		raw_failures = []

	records: list[dict[str, Any]] = []

	for item in raw_successes:
		if not isinstance(item, dict):
			continue

		response = item.get("response", {})
		if not isinstance(response, dict):
			response = {}

		row: dict[str, Any] = dict(response)
		row["source_path"] = row.get("source_path") or item.get("source_path", "")
		row["model_name"] = row.get("model_name") or _path_part(row.get("source_path", ""), 0)
		row["product_id"] = row.get("product_id") or _path_part(row.get("source_path", ""), 1)
		row["client_image_path"] = str(item.get("image_path", ""))
		row["result_image_path"] = row.get("result_image_path") or item.get("result_image_path")
		row["result_metadata_path"] = row.get("result_metadata_path") or item.get("result_metadata_path")

		row["avg_score"] = _as_float(row.get("avg_score", item.get("avg_score")), 0.0)

		scores = row.get("scores", [])
		if isinstance(scores, list):
			row["scores"] = [_as_float(score, 0.0) for score in scores]
		else:
			row["scores"] = []

		step_number = _as_int(row.get("step_number"))
		if step_number is None:
			step_number = _extract_step_number(row.get("source_path"))

		row["step_number"] = step_number
		row["_step"] = step_number
		row["_avg_score"] = _as_float(row.get("avg_score"), 0.0)
		row["_model"] = str(row.get("model_name", ""))
		row["_product"] = str(row.get("product_id", ""))

		records.append(row)

	report_total = _as_int(report.get("total"))
	report_success = _as_int(report.get("success"))
	report_failed = _as_int(report.get("failed"))
	report_mean = _as_float(report.get("mean_avg_score"), 0.0)

	if report_total is None:
		report_total = len(raw_successes) + len(raw_failures)
	if report_success is None:
		report_success = len(raw_successes)
	if report_failed is None:
		report_failed = len(raw_failures)
	if report_mean <= 0.0 and records:
		report_mean = mean([row["_avg_score"] for row in records])

	summary = {
		"server_endpoint": report.get("server_endpoint", ""),
		"data_dir": report.get("data_dir", ""),
		"total": report_total,
		"success": report_success,
		"failed": report_failed,
		"mean_avg_score": report_mean,
		"report_path": str(report_path),
	}

	return records, raw_failures, summary, errors


def _render_summary(
	records: list[dict[str, Any]],
	filtered: list[dict[str, Any]],
	failures: list[dict[str, Any]],
	summary: dict[str, Any],
	errors: list[dict[str, str]],
):
	col1, col2, col3, col4, col5 = st.columns(5)
	col1.metric("Sent Total", summary.get("total", 0))
	col2.metric("Success", summary.get("success", 0))
	col3.metric("Failed", summary.get("failed", 0))
	col4.metric("Filtered", len(filtered))
	col5.metric("Load Errors", len(errors))

	left_col, right_col = st.columns(2)
	left_col.metric("Mean avg_score", f"{_as_float(summary.get('mean_avg_score'), 0.0):.6f}")
	right_col.metric("Shown Failures", len(failures))


def _render_table(filtered: list[dict[str, Any]]):
	rows = [
		{
			"model_name": row.get("model_name"),
			"product_id": row.get("product_id"),
			"step_number": row.get("step_number"),
			"avg_score": round(row.get("_avg_score", 0.0), 6),
			"source_path": row.get("source_path"),
			"client_image_path": row.get("client_image_path"),
			"result_metadata_path": row.get("result_metadata_path"),
		}
		for row in filtered
	]
	st.dataframe(rows, width="stretch", hide_index=True)


def _record_label(row: dict[str, Any]) -> str:
	model = row.get("model_name", "-")
	product = row.get("product_id", "-")
	step = row.get("step_number", "-")
	avg = row.get("_avg_score", 0.0)
	src = row.get("source_path", "-")
	return f"{model}/{product} | step={step} | avg={avg:.6f} | {src}"


def main():
	st.set_page_config(page_title="Client Inspection Viewer", layout="wide")
	st.title("Client Inspection Viewer")
	st.caption("client_send_report.json 기반으로 검사 결과를 필터링하고 상세 내용을 확인합니다.")

	root_dir = Path(__file__).resolve().parent

	if "run_server_url" not in st.session_state:
		st.session_state["run_server_url"] = "http://127.0.0.1:8000"
	if "run_data_dir" not in st.session_state:
		st.session_state["run_data_dir"] = "data"
	if "run_timeout_sec" not in st.session_state:
		st.session_state["run_timeout_sec"] = 60.0
	if "run_limit" not in st.session_state:
		st.session_state["run_limit"] = 0
	if "run_pretty" not in st.session_state:
		st.session_state["run_pretty"] = False
	if "last_client_run" not in st.session_state:
		st.session_state["last_client_run"] = None

	with st.sidebar:
		st.header("Run Sender")
		st.text_input("Server URL", key="run_server_url")
		st.text_input("Data Dir", key="run_data_dir")
		st.number_input("Timeout (sec)", min_value=1.0, step=1.0, key="run_timeout_sec")
		st.number_input("Limit (0 means all)", min_value=0, step=1, key="run_limit")
		st.checkbox("Pretty response log", key="run_pretty")
		run_clicked = st.button("Run client.py", type="primary")

		st.divider()
		st.header("Filter")
		report_path_text = st.text_input("Report Path", value=str(DEFAULT_REPORT_PATH))
		if st.button("Refresh"):
			load_client_report.clear()
			st.rerun()

	if run_clicked:
		with st.spinner("client.py 실행 중... 이미지 전송을 진행합니다."):
			try:
				run_result = _run_client_sender(
					root_dir=root_dir,
					server_url=str(st.session_state["run_server_url"]),
					data_dir=str(st.session_state["run_data_dir"]),
					timeout_sec=float(st.session_state["run_timeout_sec"]),
					limit=int(st.session_state["run_limit"]),
					report_path=report_path_text,
					pretty=bool(st.session_state["run_pretty"]),
				)
			except Exception as exc:  # noqa: BLE001
				run_result = {
					"command": "",
					"returncode": -1,
					"stdout": "",
					"stderr": str(exc),
				}

		st.session_state["last_client_run"] = run_result
		load_client_report.clear()
		st.rerun()

	records, failures, summary, errors = load_client_report(report_path_text, str(root_dir))

	last_run = st.session_state.get("last_client_run")
	if isinstance(last_run, dict):
		returncode = _as_int(last_run.get("returncode"))
		if returncode == 0:
			st.success("client.py 실행이 완료되었습니다.")
		else:
			st.error(f"client.py 실행 실패 (code={last_run.get('returncode')})")

		with st.expander("Last Run Log", expanded=returncode != 0):
			command = str(last_run.get("command", "")).strip()
			if command:
				st.code(command)

			stdout_text = str(last_run.get("stdout", "")).strip()
			stderr_text = str(last_run.get("stderr", "")).strip()

			if stdout_text:
				st.markdown("**stdout**")
				st.code(stdout_text)
			if stderr_text:
				st.markdown("**stderr**")
				st.code(stderr_text)

	if summary:
		st.caption(f"Server Endpoint: {summary.get('server_endpoint', '-')}")
		st.caption(f"Data Dir: {summary.get('data_dir', '-')}")
		st.caption(f"Report: {summary.get('report_path', '-')}")

	if errors:
		st.warning("리포트 로드 중 오류가 발생했습니다.")
		st.dataframe(errors, width="stretch", hide_index=True)

	if not records and not failures:
		st.info("표시할 결과가 없습니다. 먼저 client.py를 실행해 리포트를 생성하세요.")
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

	filtered: list[dict[str, Any]] = []
	for row in product_filtered:
		if selected_steps and row["_step"] not in selected_steps:
			continue
		if row["_avg_score"] < min_avg_score:
			continue
		if keyword and keyword not in str(row.get("source_path", "")).lower():
			continue
		filtered.append(row)

	_render_summary(records, filtered, failures, summary, errors)

	st.subheader("Result Table")
	_render_table(filtered)

	if not filtered:
		st.info("필터 조건에 맞는 성공 결과가 없습니다.")
	else:
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
		result_img_path = _to_abs_path(selected.get("result_image_path"), root_dir)
		ref_img_path = _to_abs_path(selected.get("reference_image_path"), root_dir)

		with img_col1:
			st.markdown("**Result Image**")
			if result_img_path and result_img_path.exists():
				st.image(str(result_img_path), width="stretch")
				st.code(str(result_img_path))
			else:
				st.warning("클라이언트 PC에서 결과 이미지 경로에 접근할 수 없습니다.")
				st.code(str(result_img_path) if result_img_path else "N/A")

		with img_col2:
			st.markdown("**Reference Image**")
			if ref_img_path and ref_img_path.exists():
				st.image(str(ref_img_path), width="stretch")
				st.code(str(ref_img_path))
			else:
				st.warning("클라이언트 PC에서 기준 이미지 경로에 접근할 수 없습니다.")
				st.code(str(ref_img_path) if ref_img_path else "N/A")

	st.subheader("Failure Table")
	if failures:
		failure_items = [item for item in failures if isinstance(item, dict)]
		if failure_items:
			failure_rows = [
				{
					"image_path": item.get("image_path"),
					"source_path": item.get("source_path"),
					"stage": item.get("stage"),
					"status_code": item.get("status_code"),
					"error": item.get("error"),
				}
				for item in failure_items
			]

			st.dataframe(failure_rows, width="stretch", hide_index=True)
			selected_failure = st.selectbox(
				"Select Failure",
				options=list(range(len(failure_rows))),
				format_func=lambda i: f"{failure_rows[i].get('source_path') or failure_rows[i].get('image_path')}",
			)
			st.json(failure_items[selected_failure], expanded=False)
		else:
			st.info("표시 가능한 실패 항목이 없습니다.")
	else:
		st.info("실패 항목이 없습니다.")


if __name__ == "__main__":
	main()
