# README

## 읽는 순서

### 1단계: 진입점 파악

먼저 `pyproject.toml`의 `[project.scripts]` 항목을 봅니다.

```toml
ssdbench = "ssdbench.cli:app"
```

`ssdbench` 명령을 실행하면 `src/ssdbench/cli.py`의 `app` 객체가 호출된다는 뜻입니다. 즉, 모든 흐름의 시작은 `cli.py`입니다.

---

### 2단계: CLI의 `run` 명령

`cli.py`에서 `run_cmd` 함수 하나만 보면 됩니다.

`list`, `show`, `scenarios`는 조회/보조 명령이라 나중에 봐도 됩니다. `run_cmd` 안에 M1의 전체 파이프라인이 순서대로 나열되어 있습니다.

---

### 3단계: 각 단계가 부르는 모듈

`run_cmd` 안에서 호출되는 함수를 따라가면서 그 정의를 보는 순서로 읽으시면 됩니다.

이 순서가 곧 이 프로젝트의 논리적 아키텍처 순서와 일치합니다.

---

# 핵심 흐름

`ssdbench run 4k_randread --device /dev/nvme0n1`

한 줄이 실행될 때 내부에서 벌어지는 일을 8단계로 정리하면 다음과 같습니다.

## 1. 시나리오 로딩 (`scenarios/loader.py`)

`_resolve_scenario`가 호출됩니다.

인자가 파일 경로면 그 파일을 읽고, 그렇지 않으면 카탈로그 디렉토리(`scenarios/catalog/`)에서 이름으로 찾습니다.

YAML 파싱 후 `schema.json`으로 검증하고, 통과하면 Pydantic 모델인 `Scenario` 객체를 반환합니다.

이때 원본 YAML 텍스트를 `raw_yaml` 필드에 함께 담습니다. 이건 나중에 재현성을 위해 실행 디렉토리에 사본으로 저장하기 위해서입니다.

---

## 2. fio job file 렌더링 (`scenarios/renderer.py`)

`render_fio_job`이 `Scenario` 객체와 디바이스 경로를 받아 fio가 이해하는 ini 형식 문자열을 만듭니다.

여기서 중요한 점은 사용자가 지정하지 않은 옵션이 이 함수에서 강제로 삽입된다는 것입니다.

- `time_based=1`
- `group_reporting=1`
- `randrepeat=0`
- `norandommap=1`

사용자가 실수로 빠뜨릴 수 없게 만드는 것이 설계 의도입니다.

---

## 3. 실행 디렉토리 생성 (`storage/run_store.py`)

`RunStore.create_run`이 타임스탬프, 시나리오 이름, 디바이스 이름, 짧은 UUID를 조합해 새 디렉토리를 만듭니다.

예를 들면

```text
20260707T143000_4k_randread_nvme0n1_a1b2c3
```

형태입니다.

반환되는 `RunDirectory` 객체는 이 디렉토리 안의 각 파일 경로를 프로퍼티로 제공하는 얇은 핸들입니다.

---

## 4. Manifest 조기 기록

실제 fio 실행 전에 manifest를 먼저 씁니다.

`status="running"` 상태로 기록합니다.

이렇게 하는 이유는 실행 중 프로세스가 죽거나 사용자가 `Ctrl-C`를 눌러도 이 실행이 존재했다는 흔적이 남게 하기 위함입니다.

실행이 정상적으로 끝나면 이 manifest를 `status="completed"`로 덮어 씁니다.

---

## 5. 시스템 메타데이터 수집 (`runner/metadata.py`)

`collect_metadata`가 세 종류의 정보를 모읍니다.

- 호스트 정보
  - hostname
  - 사용자
  - 커널
  - CPU 모델
  - 메모리
- 디바이스 정보
  - 블록 디바이스 여부
  - 크기
  - 모델
  - 시리얼
  - NVMe 여부
- 도구 정보
  - fio 버전과 경로
  - ssdbench 버전

디바이스 모델과 시리얼은

```text
/sys/block/<device>/device/model
/sys/block/<device>/device/serial
```

을 읽어서 얻습니다.

모든 항목이 best effort입니다.

읽지 못하면 `None`으로 남기고, 예외를 던져 실행을 중단시키지는 않습니다.

알 수 없는 필드는 알 수 없다고 명시적으로 남기는 것이 방침입니다.

---

## 6. fio 실행 (`runner/fio_runner.py`)

`run_fio`가 `subprocess`로 fio를 띄웁니다.

이 함수의 핵심 세부 사항은 세 가지입니다.

### 첫째

`--output-format=json --output=<파일>`을 인자로 넘겨서 결과를 JSON으로 파일에 직접 쓰게 합니다.

stdout에는 fio가 정상 로그를 남기는데 이건 별도 파일로 리다이렉트합니다.

결과와 로그를 파일로 분리하는 것이 핵심입니다.

### 둘째

`start_new_session=True`로 새 프로세스 그룹에서 fio를 실행합니다.

이렇게 하면 CLI에 대한 `Ctrl-C`가 fio를 즉시 죽이지 않고, CLI가 `KeyboardInterrupt`를 잡아서 자기가 원하는 방식으로 fio에 `SIGINT`를 전달할 수 있습니다.

### 셋째

`subprocess.Popen`과 `wait(timeout=...)`을 조합해서 시나리오의 예상 실행시간에 여유(120초 기본)를 더한 timeout을 걸어둡니다.

Timeout이 발동하면 `SIGTERM` 후 필요시 `SIGKILL`로 정리합니다.

---

## 7. JSON 파싱 (`_parse_fio_json`)

fio가 남긴 JSON 파일을 읽어서 `FioResult` 데이터클래스로 변환합니다.

`data["jobs"][0]`에서 시작해 read와 write 방향별로

- iops
- bw_bytes
- clat_ns.mean

을 추출합니다.

Percentile은 fio가 `"99.000000"`, `"99.900000"` 같은 문자열 키로 저장하므로, 그걸 `float`으로 변환해 매칭하는 로직이 들어있습니다.

원본 JSON 전체는 `raw` 필드에 담아둬서 나중에 필요할 때 접근 가능하게 남깁니다.

---

## 8. Manifest 완료 처리와 요약 생성 (`reporting/summary.py`)

Manifest를 `status="completed"`로 갱신하고 종료 시각을 기록합니다.

`render_summary_markdown`이 `FioResult`와 메타데이터를 조합해 사람이 읽기 좋은 Markdown 표를 만들어 `summary.md`로 저장합니다.

`render_summary_table`은 같은 정보를 rich Table로 만들어 터미널에 출력합니다.

---

# 데이터 흐름

```text
YAML (카탈로그 또는 파일)
  → Scenario (Pydantic 모델)
  → fio job file (ini 텍스트)
  → fio subprocess 실행
  → fio_output.json (파일)
  → FioResult (데이터클래스)
  → summary.md + 터미널 표
```

각 화살표가 하나의 모듈에 해당합니다.

그래서 모듈 간 결합이 낮고 각각 독립적으로 테스트할 수 있습니다.

실제로 `tests/`의 파일 이름을 보시면 각 변환 단계에 하나씩 대응하는 것을 확인하실 수 있습니다.

---

# 읽기 팁

`Scenario`가 어디서 만들어져서 어디로 흘러가는지를 따라가는 것이 이 코드베이스를 이해하는 가장 좋은 방법입니다.

이 객체 하나가 시작부터 끝까지 관통합니다.

- `render_fio_job`의 입력
- `run_dir.write_scenario_yaml`로 원본 저장
- 이름은 manifest에도 기록
- 요약 생성에도 사용

반대로 `RunDirectory` 객체는 흐름의 반대편 끝에 있는 물리적 저장의 추상화입니다.

각 파일 경로를 프로퍼티로 노출하는 것 외에 다른 로직은 거의 없습니다.

이 두 축(Scenario는 논리적 정의, RunDirectory는 물리적 저장)이 `run_cmd`에서 만나 실행이 이루어진다고 이해하시면 전체 그림이 잡힙니다.