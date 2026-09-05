"""
data/bids.json, data/awards.json, data/status.json, docs/index.html, docs/awards.html
변경사항을 커밋하고 푸시합니다. bash든 PowerShell이든 상관없이 동일하게 동작하도록
파이썬으로 작성했습니다 (GitHub Actions가 리눅스든 사용자 Windows PC든 문제없이 돌아감).

2026-09-05: 공고 수집(main.py) 단계가 1시간 넘게 걸리는 경우가 있는데, 그 사이
누군가 main 브랜치에 다른 커밋(예: 문서 업데이트)을 푸시하면 여기서 만든 커밋의
git push가 non-fast-forward로 거절된다. 예전 코드는 run()의 반환코드를 확인하지
않아 push 실패를 조용히 무시했고, 그 결과 그날 수집한 정상 데이터가 원격에 반영
안 된 채 통째로 유실됐다(2026-09-04 KEPCO 1051건 수집 성공 건이 실제 사례).
이제 push가 거절되면 최신 원격 커밋을 rebase로 받아온 뒤 재시도하고, 그래도
실패하면 실행 자체를 실패 처리해서 GitHub이 이메일로 알려주게 한다.
"""

import subprocess
import sys
from datetime import datetime


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode


def push_with_retry(max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        if run(["git", "push"]) == 0:
            return True
        print(f"[commit_and_push] push 실패 (시도 {attempt}/{max_attempts}) - "
              f"원격에 새 커밋이 있을 수 있어 rebase 후 재시도합니다.")
        run(["git", "pull", "--rebase"])
    return False


def main():
    run(["git", "config", "user.name", "bid-monitor-bot"])
    run(["git", "config", "user.email", "bot@users.noreply.github.com"])
    run(["git", "add", "data/bids.json", "data/awards.json", "data/status.json", "docs/index.html", "docs/awards.html"])

    # 변경사항이 있는지 확인 (있으면 exit code 1)
    diff_code = run(["git", "diff", "--quiet", "--cached"])
    if diff_code == 0:
        print("변경사항 없음, 커밋 생략")
        return

    msg = f"chore: 자동 공고 업데이트 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    run(["git", "commit", "-m", msg])

    if not push_with_retry():
        print("[commit_and_push] git push가 계속 실패해 이번에 수집한 데이터가 "
              "원격에 반영되지 못했습니다. 실행을 실패로 표시합니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
