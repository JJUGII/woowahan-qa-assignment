# 우아한형제들 Senior QA Engineer 사전과제

지원자: 주기영

## 제출물

- [전체 답안 PDF](<docs/주기영_Senior QA Engineer(Test Automation Specialist)_사전과제.pdf>) / [HTML](docs/QA_자동화_검토보고서.html)
- **문제2:** [설계와 실행 방법](problem2_inventory_api/README.md) / [TC 명세서](problem2_inventory_api/docs/B마트_재고_API_TestCase_무작위반복.xlsx) / [테스트 코드](problem2_inventory_api/test_stock_api.py)
- **문제3:** [문제점과 설계](problem3_e2e_refactoring/README.md) / [리팩토링 코드](problem3_e2e_refactoring/OrderFlowTest.kt)
- **문제4:** [Android Script Studio 사용법](problem4_ai_qa_tool/README.md) / [프롬프트](problem4_ai_qa_tool/prompts/prompt.md) / [가상 입력 예제](problem4_ai_qa_tool/examples/export_sample.py) / [Windows EXE 풀 패키지](https://github.com/JJUGII/woowahan-qa-assignment/releases/download/submission/AndroidScriptStudio-Windows-x64.zip)

전체 압축 제출본에는 `problem4_ai_qa_tool/release/AndroidScriptStudio-Windows-x64.zip`이 포함되어 있습니다. GitHub에서는 Releases에서 내려받을 수 있습니다.

## 실행 방법

| 대상 | 실행 방법 |
| --- | --- |
| 문제2 기본 API 시험 | [run_tests.bat](problem2_inventory_api/run_tests.bat) |
| 문제2 동시 주문 50회 반복 | [run_concurrency.bat](problem2_inventory_api/run_concurrency.bat) |
| 문제3 | 실행 환경 없이 설계 의도를 보여주는 Kotlin 코드 |
| 문제4 | ZIP 전체를 해제한 뒤 AndroidScriptStudio.exe 실행 |

[run_all_tests.bat](run_all_tests.bat)는 문제2 기본 시험과 동시 주문 반복 시험을 실행합니다. [시험성적서 모음](시험성적서_모음.html)에서 결과를 확인할 수 있습니다. 문제별 실행 조건과 명령은 각 README에 있습니다.

문제2 배치는 Python과 라이브러리를 준비합니다. 최초 설치에는 인터넷이 필요하며 Python 자동 설치에는 winget을 사용합니다. 소스용 배치는 루트의 `tools/`도 사용하므로 폴더 구조를 유지하세요.

## 문제2 실행 기록

고유 TC 18개, 매개변수를 포함한 기본 실행 25건, 별도 동시 주문 반복 50회의 기록을 제공합니다. 시험 대상은 로컬 HTTP 스텁입니다. 엑셀의 결과는 저장된 실행 기록이며 테스트 실행 시 자동 갱신되지 않습니다.

## 사용 도구와 AI 활용

ChatGPT와 Codex를 답안 검토, 테스트 케이스와 코드 작성, 리팩토링, 문서 정리에 활용했습니다. 문제4는 기존 Universal 프로젝트에 AI 지원을 추가한 도구이며, 기능과 사용법은 문제4 README에 설명했습니다.
