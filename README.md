# ssdbench

fio 위에 얹은 팀 공용 SSD 벤치마크 프레임워크. 팀원이 fio 파라미터를 몰라도
표준 시나리오로 SSD 성능을 재현 가능하게 측정할 수 있게 하는 것이 목표.

## Install

```bash
pip install -e .
```

fio 자체는 별도로 설치되어 있어야 함.

```bash
# Ubuntu
sudo apt install fio

# RHEL
sudo dnf install fio
```

## Quick start

```bash
# 사용 가능한 시나리오 확인
ssdbench scenarios

# 4K 랜덤 읽기 시나리오를 /dev/nvme0n1 대상으로 실행
sudo ssdbench run 4k_randread --device /dev/nvme0n1

# 저장된 실행 목록
ssdbench list

# 특정 실행의 요약 보기
ssdbench show <run_id>
```

`sudo`가 필요한지 여부는 대상 디바이스 접근 권한에 따라 다름. raw block device는
보통 root 권한을 요구.

## Where results go

기본적으로 `~/.ssdbench/runs/` 아래 실행별 디렉토리로 저장됨.

```
~/.ssdbench/runs/20260707T143000_4k_randread_nvme0n1_a1b2c3/
    manifest.json       # run id, scenario, device, 시각
    metadata.json       # 호스트, 커널, fio 버전, 디바이스 정보
    scenario.yaml       # 실행 시점의 시나리오 원본 사본
    fio_job.fio         # 렌더링된 fio job file
    fio_output.json     # fio JSON 출력 원본
    summary.md          # 사람이 읽기 위한 요약
    stdout.log
    stderr.log
```

환경 변수 `SSDBENCH_RUNS_DIR`로 저장 위치를 바꿀 수 있음.

## Scenarios

M1 시점의 카탈로그.

| name | 목적 |
|---|---|
| `4k_randread` | 4K 랜덤 읽기 IOPS |
| `4k_randwrite` | 4K 랜덤 쓰기 IOPS |
| `seq_read_128k` | 128K 순차 읽기 대역폭 |
| `seq_write_128k` | 128K 순차 쓰기 대역폭 |
| `qd1_randread_latency` | QD1 랜덤 읽기 지연시간 |

임의의 시나리오 YAML 파일을 인자로 넘겨서 실행할 수도 있음.

```bash
ssdbench run ./my_scenario.yaml --device /dev/nvme0n1
```

## What M1 does not do yet

- 여러 실행 간 비교와 통계 검정
- Preconditioning 자동화 (사용자가 스크립트로 직접 챙겨야 함)
- 환경 검증 (governor, NUMA, 대상 디바이스의 다른 I/O 여부)
- 자동 스윕
