"""
data/bids.json, data/awards.json, data/status.json, docs/index.html, docs/awards.html
변경사항을 커밋하고 푸시합니다. bash든 PowerShell이든 상관없이 동일하게 동작하도록
파이썬으로 작성했습니다 (GitHub Actions가 리눅스든 사용자 Windows PC든 문제없이 돌아감).
"""

import subprocess
from datetime import datetime


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode


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
    run(["git", "push"])


if __name__ == "__main__":
    main()
