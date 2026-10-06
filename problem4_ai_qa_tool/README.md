# 문제 4 - Android Script Studio

**기존에 테스트 자동화를 구축하면서 가장 많은 시간이 들었던 작업은 테스트 스크립트 작성이었습니다. 화면 요소를 찾고 같은 동작과 검증 코드를 반복해서 작성하는 시간을 줄이고자 Universal 프로젝트를 만들기 시작했습니다. 이번 과제를 받고 기존 기능에 AI 지원을 추가한 Android Script Studio를 제출합니다.**

**휴대폰 화면에서 수행한 동작을 기록해 Python 또는 Kotlin 테스트 코드로 저장하는 도구입니다. 추가한 AI 기능은 테스트 목표와 현재 화면을 보고 다음 동작을 제안합니다. 실행한 동작을 기록하고, 기록을 바탕으로 테스트 코드를 생성합니다.**

프로토타입 소스 코드와 프롬프트, [Windows EXE 풀 패키지](https://github.com/JJUGII/woowahan-qa-assignment/releases/download/submission/AndroidScriptStudio-Windows-x64.zip)를 함께 제출합니다. 실행 및 설정 방법은 아래에 정리했습니다.

## 주요 기능과 동작 구조

- **수동 작성:** Android 화면 요소를 선택해 클릭, 입력, 표시 확인, 뒤로가기, 스크롤, 대기를 기록
- **AI 지원:** 목표와 현재 화면을 보고 다음 동작 추천 또는 자동 진행. 실제 화면과 대상 확인 후 실행
- **코드 저장:** 완료된 기록을 Python(Appium) 또는 Kotlin(UIAutomator)과 시나리오 파일로 저장
- **사용량:** 토큰 사용량과 추정 API 비용 표시

`목표/도착 문구 입력 → 화면 확인 → AI 제안 → 대상 확인 및 실행 → 결과 기록 → 코드 저장`

AI는 정해진 형식의 다음 동작을 제안하며 임의 코드를 실행하지 않습니다. 프로그램이 응답 형식, 대상 중복, 화면 변경과 실제 도착 문구를 확인하고 템플릿으로 코드를 생성합니다.

압축 제출본에는 `release/AndroidScriptStudio-Windows-x64.zip`도 포함되어 있습니다.

## EXE 실행과 설정

1. [Windows x64 풀 패키지](https://github.com/JJUGII/woowahan-qa-assignment/releases/download/submission/AndroidScriptStudio-Windows-x64.zip)를 내려받아 쓰기 가능한 짧은 경로에 **전체 압축 해제**합니다. EXE만 따로 옮기지 마세요.
2. `AndroidScriptStudio/AndroidScriptStudio.exe`를 실행합니다.
3. Android 휴대폰의 **개발자 옵션 → USB 디버깅**을 켜고 USB 연결 후 PC 승인을 누릅니다. 인식되지 않으면 제조사 USB 드라이버를 설치합니다.
4. 프로그램의 **휴대폰 연결**에서 단말을 연결합니다. 시험할 앱과 계정, 시작 화면은 직접 준비합니다.
5. **AI 설정**에서 서비스와 본인의 API 키를 입력하고 **모델 목록 조회** 후 모델을 선택합니다. 목록을 지원하지 않으면 모델명을 직접 입력합니다. AI 호출에는 인터넷과 별도 사용료가 필요합니다.
6. **목표와 도착 문구**를 입력하고 수동 또는 AI 지원으로 작성합니다. 기록을 검토한 뒤 Python/Kotlin으로 저장합니다.

작성기 실행에 필요한 Python 런타임, Node.js, Java JDK, ADB, Android Build Tools 36.0.0, Appium 3.8.0과 UiAutomator2 8.2.0을 동봉했습니다. 별도 개발 도구 설치와 시스템 환경 변수 변경 없이 실행하도록 구성했습니다. 개인 API 키, 로그와 단말 설정은 포함하지 않았습니다.

`환경진단.cmd`는 GUI, 동봉 도구와 Appium 서버를 검사하고 `LOG/portable-self-test.json`을 엽니다. `ok: true`가 정상입니다. 실제 휴대폰 조작이나 AI 호출은 하지 않습니다.

## 소스 실행과 구조

- [run_app.bat](run_app.bat): 소스 실행에 필요한 단말 도구 준비 후 프로그램 실행
- [setup_device.bat](setup_device.bat): 단말 도구만 준비

소스용 배치에는 저장소 루트의 `tools/`도 필요합니다. 배포 EXE의 동봉 도구와 소스용 배치가 설치하는 도구 버전은 다를 수 있습니다. 재빌드는 [build_exe.bat](build_exe.bat)과 [tools/build_portable.py](tools/build_portable.py)를 사용하며 빌드 PC에 Python 패키지, PyInstaller와 스크립트에 지정된 도구가 필요합니다.

- `main_recorder.py`: 실제 실행 시작점 (`main.py`는 제출용 연결 파일)
- `recorder/writer_gui.py`: 수동 작성과 AI 지원 화면
- `recorder/writer_agent.py`: 화면 정보 정리, AI 다음 동작 제안과 응답 검사
- `recorder/writer_device.py`: 단말 연결, 대상 재확인과 동작 실행
- `recorder/writer_session.py`: 완료 동작 기록과 Python/Kotlin 저장
- `recorder/writer_usage.py`: 사용량과 비용 기록
- `recorder/portable_runtime.py`: 동봉 실행 도구 설정과 EXE 환경 진단
- [prompts/prompt.md](prompts/prompt.md): 실제 AI 프롬프트 사본
- [examples/](examples/): 단말/AI 호출 없이 볼 수 있는 가상 입력과 생성 코드 예제

기존 Universal 프로젝트에 AI 지원 기능을 추가했습니다.

## 단말과 API 키 없이 예제 확인

소스 실행 환경을 준비한 뒤 가상 XML로 Python/Kotlin 표시 검증 코드를 생성할 수 있습니다. 실제 휴대폰이나 AI API를 호출하지 않습니다.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe examples/export_sample.py --output-dir examples/demo_output
```

같은 이름의 결과 파일이 있으면 덮어쓰지 않습니다. 다시 실행할 때는 새 출력 폴더를 지정합니다. 소스 프로그램은 `.venv\Scripts\python.exe main.py`로 실행합니다.

## 지원 범위

이미지 전용 화면과 비밀번호 입력은 지원하지 않습니다. AI에 일부 화면 문구가 전송되므로 테스트 데이터를 사용합니다. 주문/결제/권한 관련 문구는 자동 진행을 멈추지만 문구 검사만으로 모든 위험 동작을 판별하지는 못합니다.

생성 코드는 화면 조작과 표시 검증이 중심입니다. 주문 ID, 금액 등 업무 검증은 직접 추가해야 합니다. 내보낸 Python 코드의 실행 환경이나 Kotlin용 Android Studio 테스트 프로젝트는 이 작성기 풀 패키지와 별도로 준비합니다.

## 사용 도구와 AI 활용

Python, Tkinter/CustomTkinter, Appium, ADB, UIAutomator와 PyInstaller를 사용했습니다. 기존 개인 Recorder를 바탕으로 Codex를 AI 기능, 테스트, 패키징과 문서 작성에 활용했습니다. 프로그램 안의 LLM은 다음 동작 제안을 담당하고, 기대 결과와 생성 코드 검토는 사용자가 수행합니다.

