# comfyui-codex-setup

이미 설치된 **로컬 ComfyUI를 Codex에 연결**하는 Windows/macOS 설치 스크립트입니다.
Comfy-Org의 공식 `comfy-mcp`와 `comfy-cli`를 별도 Python 가상환경에 설치하고,
Codex MCP 설정과 공식 스킬 3개, 로컬 연결용 스킬을 등록합니다.

이 프로젝트는 개인 편의 도구입니다. Comfy-Org 또는 OpenAI의 공식 설치 프로그램은 아닙니다.

## 준비

- Windows 또는 macOS
- Python **3.10–3.14** (`venv`, `pip` 사용 가능)
- Codex CLI. `codex --version`이 실행되어야 합니다. 일부 Windows Codex Desktop 설치는 자동으로 찾습니다.
- 실행 중인 ComfyUI. 기본 주소: `http://127.0.0.1:8188`

ComfyUI Desktop의 Python도 사용할 수 있습니다. 설치는 별도 환경에 하므로
ComfyUI의 torch/CUDA 및 custom-node 패키지를 바꾸지 않습니다.
macOS에서는 ComfyUI 자체가 해당 Mac의 MPS/CPU 환경에서 작동해야 합니다.
이 스크립트가 특정 이미지 모델의 GPU 호환성을 보장하지는 않습니다.

## 실행

저장소를 복제하거나 ZIP을 받아 압축을 푼 뒤, ComfyUI를 실행해 두세요.

Windows PowerShell:

```powershell
python .\setup.py
# 또는 Python Launcher 사용
py -3 .\setup.py
# Python 경로를 직접 지정하는 래퍼
.\setup.ps1 -PythonPath 'D:\ComfyUI\standalone-env\python.exe'
```

macOS Terminal:

```sh
sh setup.sh
# Python 경로를 직접 지정
PYTHON='/path/to/comfyui/.venv/bin/python' sh setup.sh
```

실행 중인 서버의 프로세스와 `/system_stats`를 이용해 활성 ComfyUI 경로를 찾습니다.
권한 제한이나 여러 인스턴스로 자동 탐지가 실패하면 **main.py가 있는 폴더**를 지정하세요.

```powershell
python .\setup.py --comfy-dir 'D:\ComfyUI\ComfyUI' --models-dir 'D:\ComfyUI-Shared\models'
```

```sh
python3 setup.py --comfy-dir '/path/to/ComfyUI' --url 'http://127.0.0.1:8188'
```

`python setup.py --help`에서 전체 옵션을 볼 수 있습니다.
Codex CLI가 PATH에 없다면 `--codex /absolute/path/to/codex`를 지정하세요.
Python이 없거나 Windows Store 바로가기만 있으면 실제 Python을 설치하거나 Desktop Python 경로를 사용하세요.

## 설정 내용과 확인

- 별도 도구 환경: Windows `%LOCALAPPDATA%\comfyui-codex\tools`, macOS `~/Library/Application Support/comfyui-codex/tools`
- 공식 도구 버전: `comfy-mcp==0.10.0`, `comfy-cli==1.22.0`
- Codex 설정: `$CODEX_HOME/config.toml`, 미지정 시 `~/.codex/config.toml`
- MCP 이름: `comfyui`, 로컬 stdio 방식
- 공식 스킬: `comfy`, `comfy-debug`, `comfy-relay` (설치한 공식 CLI 패키지에서 복사)
- 연결용 스킬: `comfy-codex-local` (이 프로젝트에서 생성)
- 스킬 위치: `$CODEX_HOME/skills`. 다른 Codex 배포의 탐색 경로를 사용한다면 `--skills-dir`로 지정하세요.

MCP handshake와 `server_info`로 서버 실행 상태, URL, 실제 checkout 경로를 검증한 뒤 설정을 저장합니다.
다른 MCP 설정과 TOML 주석을 보존하고 변경 전에 `config.toml.backup-*`을 만듭니다.
같은 설정으로 다시 실행하면 중복 항목이나 추가 설정 백업을 만들지 않습니다.
기존의 다른 `comfyui` 서버나 수정한 동명 스킬이 있으면 덮어쓰지 않고 중단합니다.

**설치 후 Codex에서 새 메시지를 보내세요.** 스킬은 다음 턴부터 사용할 수 있습니다.
MCP 도구가 나타나지 않으면 Codex를 다시 여세요. 예시 요청:

> 로컬 ComfyUI 연결 상태를 확인하고 Qwen Image 2.1 관련 노드와 설치된 모델을 조회해줘.

ComfyUI Desktop에서는 실행/재시작/업데이트를 Desktop에서 관리하세요.
Desktop의 공유 모델 경로는 `connection.json`에 기록하지만 생성된 Desktop YAML은 수정하지 않습니다.
모델 다운로드 시 공유 경로를 확인해야 합니다. MCP의 기본 다운로드 위치는 checkout 안의 `models`일 수 있습니다.

모델 가중치, INT4 변환, BFS LoRA, custom nodes, ComfyUI 자체는 이 스크립트의 설치 범위에 포함되지 않습니다.
유료 Comfy Cloud/partner API 설정도 하지 않습니다. 이 스크립트는 로컬 연결 설정을 재현합니다.
직접 의존성은 고정하지만 전이 의존성까지 고정한 lockfile은 아니므로 미래의 설치 결과는 달라질 수 있습니다.

## 검사와 복구

```sh
python -m pip install -r requirements-tools.txt
python -m unittest -v
```

GitHub Actions는 Windows/macOS, Python 3.10/3.13에서 설정 보존, 중복 실행,
충돌 처리, Desktop 공유 경로 처리 및 래퍼를 검사합니다. GPU 이미지 생성 테스트는 아닙니다.
실제 기기 설치에서는 별도로 실제 로컬 MCP 연결을 검증합니다.

연결 제거: `codex mcp remove comfyui` 후 설치한 스킬 폴더와 도구 환경을 필요한 경우 수동으로 제거하세요.
Codex의 사용자 설정은 백업 파일과 비교하여 복구할 수 있습니다.
기기별 `connection.json`, 설정 백업, 자격 증명은 GitHub에 올리지 마세요.

## 출처와 라이선스

- [공식 Comfy MCP](https://github.com/Comfy-Org/comfy-mcp)
- [공식 Comfy CLI 및 스킬](https://github.com/Comfy-Org/comfy-cli)
- [Codex MCP 문서](https://developers.openai.com/codex/mcp)
- [Codex 스킬 문서](https://developers.openai.com/codex/skills)

이 저장소의 설치 코드와 연결용 스킬 템플릿은 MIT입니다.
설치되는 외부 패키지와 공식 스킬에는 각 원저작자의 라이선스가 적용됩니다.
