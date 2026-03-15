# Parallel Image Similarity Inspector

FastAPI 서버(`/inspect`)에 이미지(Base64)를 보내면, `templates/`의 **step 템플릿 이미지**를 기준으로 템플릿 매칭을 수행하고 다음을 생성합니다.

- 결과 시각화 이미지: `outputs/<model>/<product>/<원본파일명>.jpg`
- 메타데이터 JSON: `outputs/<model>/<product>/<원본파일명>.json`

추가로 아래 도구가 포함되어 있습니다.

- `client.py`: `data/` 폴더의 이미지를 서버로 **일괄 전송**(배치)
- `ui.py`: `outputs/` 결과(JSON/이미지)를 **필터링/조회**하는 Streamlit 뷰어
- `client_ui.py`: Streamlit에서 `client.py`를 **버튼으로 실행**하고 전송 리포트를 조회

---

## 요구사항

- Python **3.13+** (프로젝트 설정: `.python-version`)
- 패키지 매니저
  - 권장: **uv** (`uv.lock` 포함)
  - 대안: `venv` + `pip`

> 참고: OpenCV(`opencv-python`) 설치/실행은 OS/파이썬 버전에 따라 시간이 걸릴 수 있습니다.

---

## 설치

### 방법 A) uv (권장)

프로젝트 루트에서:

```powershell
uv sync
```

### 방법 B) venv + pip

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install fastapi uvicorn streamlit numpy opencv-python pydantic requests
```

---

## 빠른 시작 (로컬 실행)

### 1) 폴더 준비

입력 이미지와 템플릿이 아래 규칙을 만족해야 합니다.

- 입력 이미지: `data/<model_name>/<product_id>/step_<n>.jpg`
- 템플릿 이미지: `templates/<model_name>/<product_id>/step_tem_<n>.jpg`

현재 예시 데이터는 아래에 존재합니다.

- `data/3029C003AA/2EQ16144/step_0.jpg` ~ `step_14.jpg`
- `templates/3029C003AA/2EQ16144/step_tem_0.jpg` ~ `step_tem_14.jpg`

### 2) 서버 실행 (FastAPI)

```powershell
# uv 사용 시
uv run uvicorn server:app --reload --host 127.0.0.1 --port 8000

# 또는 venv/pip 사용 시
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

- 서버 문서(UI): `http://127.0.0.1:8000/docs`

### 3) 배치 전송 (client.py)

다른 터미널에서:

```powershell
# uv 사용 시
uv run python client.py --server-url http://127.0.0.1:8000 --data-dir data

# 또는 venv/pip 사용 시
python client.py --server-url http://127.0.0.1:8000 --data-dir data
```

옵션:

- `--limit 10`: 상위 N장만 전송
- `--timeout 60`: 요청 타임아웃(초)
- `--report-path client_send_report.json`: 전송 결과 리포트 저장 경로
- `--pretty`: 응답 JSON을 콘솔에 보기 좋게 출력

### 4) 결과 확인 (Streamlit)

#### A) outputs 폴더 뷰어 (ui.py)

```powershell
uv run streamlit run ui.py
# 또는
streamlit run ui.py
```

#### B) 전송 리포트 뷰어 + 실행기 (client_ui.py)

```powershell
uv run streamlit run client_ui.py
# 또는
streamlit run client_ui.py
```

---

## 데이터 / 템플릿 규칙 (중요)

### 입력 이미지 경로 규칙

서버/클라이언트는 **상대경로** `source_path`를 기준으로 모델/제품/파일명을 해석합니다.

- 폴더 구조: `<model_name>/<product_id>/<image_file>` (최소 3단계)
- 파일명: **반드시** `step_<number>` 패턴을 포함해야 합니다.
  - 예: `step_0.jpg`, `step_12.png`
  - 서버의 step 추출은 `step_`(언더스코어) 형태를 기준으로 합니다.

지원 확장자: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`

### 템플릿 경로 규칙

서버는 step 번호를 기반으로 아래 중 하나를 찾습니다.

1. 단일 파일

- `templates/<model>/<product>/step_tem_<n>.jpg` (또는 png 등 지원 확장자)

2. 폴더(여러 템플릿)

- `templates/<model>/<product>/step_tem_<n>/*.jpg`

> `n`은 `step_0`처럼 0부터 시작해도 동작합니다.

---

## API

### POST /inspect

요청(JSON):

```json
{
  "model_name": "3029C003AA",
  "product_id": "2EQ16144",
  "source_path": "3029C003AA/2EQ16144/step_0.jpg",
  "image": "<base64 or data-uri>"
}
```

- `image`는 순수 Base64 문자열 또는 `data:image/jpeg;base64,...` 형태도 지원합니다.

응답(JSON) 주요 필드:

- `avg_score`: 템플릿 점수 평균(0~1 범위)
- `scores`: 템플릿별 점수 리스트(템플릿이 여러 장이면 여러 값)
- `result_image_path`: 결과 이미지 저장 경로
- `result_metadata_path`: 메타데이터 JSON 저장 경로

curl 예시:

```bash
curl -X POST "http://127.0.0.1:8000/inspect" \
	-H "Content-Type: application/json" \
	-d '{"model_name":"3029C003AA","product_id":"2EQ16144","source_path":"3029C003AA/2EQ16144/step_0.jpg","image":"..."}'
```

---

## 출력물(outputs)

서버는 `source_path`와 동일한 상대 경로 구조를 유지하여 결과를 저장합니다.

예)

- 입력: `data/3029C003AA/2EQ16144/step_3.jpg`
- 출력:
  - `outputs/3029C003AA/2EQ16144/step_3.jpg`
  - `outputs/3029C003AA/2EQ16144/step_3.json`

메타데이터 JSON 예시 키:

- `model_name`, `product_id`, `source_path`, `step_number`
- `reference_image_path`, `template_source_path`
- `output_image_path`
- `scores`, `avg_score`

---

## 프로젝트 구조

```
.
├─ server.py               # FastAPI 서버 (/inspect)
├─ client.py               # data/ 이미지 일괄 전송 CLI
├─ ui.py                   # outputs/ 결과 뷰어(Streamlit)
├─ client_ui.py            # client.py 실행 + 리포트 뷰어(Streamlit)
├─ provided_algorithm.py   # ORB 정합 + 템플릿 매칭 알고리즘(OpenCV)
├─ data/                   # 입력 이미지 (model/product/step_*.jpg)
├─ templates/              # 기준 템플릿 이미지 (step_tem_*.jpg 또는 폴더)
├─ outputs/                # 결과 이미지 + 메타데이터 JSON
├─ uv.lock                 # uv 의존성 lock
└─ pyproject.toml          # 프로젝트/의존성 정의
```

---

## 트러블슈팅

- `404 Template base directory not found` / `Step template path not found`
  - `templates/<model>/<product>/` 경로와 `step_tem_<n>` 파일(또는 폴더)이 존재하는지 확인하세요.

- `400 source_path filename must contain step_<number>`
  - 파일명이 `step_3.jpg`처럼 `step_` + 숫자 패턴을 포함해야 합니다.

- Streamlit에서 이미지가 안 보임
  - UI를 실행하는 PC에서 `result_image_path`가 실제로 접근 가능한 경로인지 확인하세요.
  - 서버와 UI가 다른 PC라면, 경로만 표시되고 이미지 로딩은 실패할 수 있습니다.

---

## 참고

- `e2e_test_inspect.py`는 과거 구조 기반의 테스트 예시로, 현재 `server.py`의 요청 스키마와 맞지 않아 그대로는 동작하지 않을 수 있습니다.
