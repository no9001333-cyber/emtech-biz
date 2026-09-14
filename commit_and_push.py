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

2026-09-11: data/bids.json처럼 큰 데이터 파일을 두 실행이 동시에 건드리면
rebase 도중 충돌이 나는데, 그러면 .git/rebase-merge가 미해결 상태로 남고
재시도 루프의 다음 "git pull --rebase" 호출이 "there is already a
rebase-merge directory" 오류로 즉시 실패한다(run #109 실패 원인). 자체
호스팅 러너는 실행 사이에 .git이 그대로 남기 때문에 이 상태가 다음 날
실행까지도 이어질 수 있다. rebase 시도 전에 이전에 남은 미해결 rebase를
먼저 정리하도록 방어 코드를 추가했다.

2026-09-14: 이 PC는 매일 저녁 꺼졌다가 아침에 다시 켜지는데, 그 사이에
실행이 중간에 끊기면(러너가 "lost communication with the server") 이
스크립트가 만든 로컬 커밋이 푸시되지 못한 채 그대로 남는다. 그러면 다음
실행이 그 커밋을 origin 위에 재적용하려다 충돌하고, 실패해도 로컬 커밋을
치우지 않아 그 다음 실행까지 똑같은 충돌이 계속 반복됐다(09-12~09-14
사흘 연속 data/bids.json 갱신 실패의 원인). push_with_retry가 끝내
실패하면 이 실행이 만든 로컬 커밋을 origin/main 기준으로 완전히 버려서
(git reset --hard) 최소한 다음 실행은 깨끗한 상태에서 시작하게 한다 -
이번에 수집한 데이터는 유실되지만, 매일 반복해서 전부 막히는 것보다는 낫다.
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
        # 이전 시도(혹은 이전 실행)에서 rebase가 충돌로 미해결 상태로 남아있으면
        # "git pull --rebase"가 시작도 못 하고 바로 실패하므로 먼저 정리한다.
        run(["git", "rebase", "--abort"])
        if run(["git", "pull", "--rebase"]) != 0:
            print("[commit_and_push] rebase 충돌 발생 - 정리하고 다음 시도로 넘어갑니다.")
            run(["git", "rebase", "--abort"])
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
              "원격에 반영되지 못했습니다. 다음 실행에 영향이 이어지지 않도록 "
              "로컬 커밋을 origin/main 기준으로 되돌립니다.")
        run(["git", "fetch", "origin", "main"])
        run(["git", "reset", "--hard", "origin/main"])
        print("[commit_and_push] 실행을 실패로 표시합니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
