Android Script Studio — Windows x64 풀 배포본

처음 실행
1. ZIP 전체를 쓰기 가능한 짧은 경로(예: C:\AndroidScriptStudio)에 압축 해제합니다.
   ZIP 내부에서 직접 실행하거나 EXE 파일만 따로 옮기면 실행되지 않습니다.
2. AndroidScriptStudio.exe를 더블클릭합니다.
3. 휴대폰에서 개발자 옵션 → USB 디버깅을 켜고 USB 케이블로 연결합니다.
4. 휴대폰에 표시되는 이 PC의 디버깅 허용 요청을 직접 승인합니다.
5. 앱에서 휴대폰 연결을 선택합니다.
6. AI 설정에서 본인의 API 키를 입력하고 [모델 목록 조회]를 누릅니다.
   [모델 선택] 오른쪽 ▼로 모델을 선택하면 등록된 모델의 단가가 자동으로 입력됩니다.
   단가가 등록되지 않은 모델만 해당 서비스의 단가를 직접 입력합니다.
   목록 조회를 지원하지 않는 서비스는 모델명을 직접 입력할 수도 있습니다.
   AI 사용에는 인터넷과 별도 API 비용이 필요합니다.

동봉 구성
- Python GUI 실행 환경 (EXE/_internal)
- Node.js, Appium, UiAutomator2 드라이버
- Java JDK, Android SDK Platform Tools(ADB), Android Build Tools 36.0.0
Python/Node.js/Java/Appium을 별도로 설치하거나 Windows 환경 변수를 설정할 필요가 없습니다.
압축 해제한 폴더 안의 도구만 사용하며 시스템 환경 변수를 변경하지 않습니다.
기존 PC의 API 키/로그/단말 기록/개인 설정은 포함하지 않았습니다.

지원 범위
- Windows 10/11 x64 데스크톱, Android USB 실단말 (UiAutomator2 8.2.0: Android 8 이상)
- ARM64/32비트 Windows, 에뮬레이터, iOS는 이 패키지의 검증 대상이 아닙니다.
- 휴대폰 제조사 USB 드라이버는 기종별로 다릅니다. Windows가 단말을 인식하지 못하면
  해당 제조사의 공식 USB 드라이버를 설치해야 합니다. 이 패키지는 커널 드라이버를 자동 설치하지 않습니다.
- 스크립트 작성, AI 지원, Python/Kotlin 내보내기를 제공하는 작성기입니다.
  내보낸 Kotlin 테스트의 빌드/실행에는 별도 Android Studio 테스트 프로젝트가 필요합니다.
  내보낸 Python 테스트의 외부 실행에는 해당 프로젝트의 Python/Appium/Airtest 실행 환경이 필요합니다.
- 앱은 데이터 초기화/주문/결제를 자동 수행하지 않습니다. 최초 실행 테스트 상태를 직접 준비하세요.

오류 확인
- 환경진단.cmd: 동봉 Node/Java/ADB/Appium/GUI/로컬 서버와 Android APK 서명/도구를 검사합니다.
  API 호출, 주문, 단말 조작은 하지 않습니다. LOG/portable-self-test.json의 ok:true가 정상입니다.
- 휴대폰 미표시: USB 케이블, 디버깅 허용, 제조사 USB 드라이버를 확인하세요.
- Appium 사용 중: 다른 Recorder의 연결을 종료한 후 다시 연결하세요.
- 쓰기 권한 오류: Program Files 대신 사용자 폴더에 전체 폴더를 옮겨 실행하세요.

라이선스
Python 패키지 고지는 THIRD_PARTY_LICENSES, Node 고지는 .tools/node/LICENSE,
Java 고지는 .tools/java/legal, Android 도구 고지는 .tools/android-sdk/platform-tools/NOTICE.txt,
Android Build Tools 고지는 .tools/android-sdk/build-tools/36.0.0/NOTICE.txt,
Appium 및 각 Node 패키지의 라이선스는 각 node_modules 하위에 포함되어 있습니다.
구성 정보는 portable_manifest.json, 빌드 시 파일 해시는 SHA256SUMS.txt에 있습니다.
진단/실행 과정에서 Appium의 경로 캐시는 현재 폴더에 맞게 다시 작성될 수 있습니다.

참고
https://github.com/appium/appium-uiautomator2-driver
https://developer.android.com/tools/releases/platform-tools
https://pyinstaller.org/en/stable/usage.html
