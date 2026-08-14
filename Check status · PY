"""
data/status.json을 읽어 소스별 상태를 출력하고, 문제 있는 소스가 있으면
비정상 종료(exit 1)합니다. daily.yml이 이 종료 코드를 보고 실행 실패로
표시해 GitHub이 자동으로 이메일 알림을 보내게 됩니다.
"""

import json
import sys


def main():
    with open("data/status.json", encoding="utf-8") as f:
        data = json.load(f)

    problems = [s for s in data["sources"] if not s["ok"]]
    for s in data["sources"]:
        mark = "OK " if s["ok"] else "FAIL"
        print(f"[{mark}] {s['source']}: {s['note']}")

    if problems:
        print(f"::warning::문제 있는 소스 {len(problems)}개가 있습니다. 대시보드 상단 상태 배지를 확인하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
