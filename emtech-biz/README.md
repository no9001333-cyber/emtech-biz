# emtech-biz — 이엠테크 입찰 자동 모니터

정부 입찰 사이트 여러 곳(나라장터, LH, 국방전자조달, 한국수자원공사, 한국전력공사, 한국철도공사)의
공고를 **매일 새벽 자동으로 수집**하고, **투찰마감이 지나면 낙찰 결과까지 자동으로 붙여서** 보여주는
웹 대시보드입니다.

- 필터: 업종·지역 전체 수집 후 화면에서 직접 필터링 (엑셀처럼)
- 참가가능 판정: 용인시 소재 기준으로 자동 판별 (전국/경기도/용인 명시 = 참가가능)
- 상태 자동 전환: 공고가 "진행중" → 마감 후 "낙찰결과 표시"로 자동 갱신
- 메모, 투찰금액 계산기(복수예가 15개 생성→4개 추첨→최종금액) 내장
- 자동 연동이 안 되는 곳(국가철도공단, 코레일 자체 시스템, 한국가스공사, 한국석유공사)은
  대시보드 상단에 바로가기 링크 제공
- **자체 오류 감지**: 소스별로 정상/문제 상태를 매일 기록하고, 문제가 있으면 GitHub Actions
  실행이 "실패"로 표시되어 GitHub이 자동으로 이메일 알림을 보냅니다 (저장소 소유자 기준).
  대시보드 상단에도 소스별 상태 배지(초록=정상, 빨강=문제)가 표시됩니다.
- **자동 업그레이드**: Dependabot이 매주 GitHub Actions 부품의 최신 버전을 확인해서
  자동으로 업데이트 PR을 만들어줍니다 (저장소 Pull requests 탭에서 확인 후 Merge하면 됩니다).

---

## 1단계. API 키 발급받기 (data.go.kr)

https://www.data.go.kr 가입 후, 아래 서비스들을 검색해서 **활용신청**하세요. 대부분 즉시 자동승인됩니다.

| 서비스명 | 용도 | GitHub Secret 이름 |
|---|---|---|
| 조달청_나라장터 입찰공고정보서비스 | 나라장터 공고 | `G2B_SERVICE_KEY` |
| 한국토지주택공사 입찰공고정보 | LH 공고 | `LH_SERVICE_KEY` |
| 방위사업청_군수품조달정보 입찰공고 | 군부대 공고 | `D2B_SERVICE_KEY` |
| 한국수자원공사_전자조달 입찰공고 | K-water 공고 | `KWATER_SERVICE_KEY` |
| 한국철도공사_조달_입찰공고 | 코레일 공고(공공데이터셋) | `KORAIL_SERVICE_KEY` |
| 국가철도공단_입찰정보DB | 철도 건설(궤도·역사·통신설비) 공고 | `KR_SERVICE_KEY` |
| 나라장터 낙찰정보서비스 | 낙찰 결과(개찰결과) | `G2B_AWARDS_SERVICE_KEY` |

**대시보드 비밀번호(선택)**: `DASHBOARD_PASSWORD`라는 Secret을 추가로 등록하면,
대시보드를 열 때 비밀번호를 먼저 입력해야 보이도록 잠글 수 있습니다. 등록 안 하면
지금처럼 비밀번호 없이 바로 보입니다. (완벽한 보안은 아니고, 검색엔진 노출 방지와
아무나 못 들어오게 막는 정도의 기본 보호입니다.)

**한국전력공사(KEPCO)**는 data.go.kr이 아니라 자체 사이트에서 별도로 발급받습니다.
- https://bigdata.kepco.co.kr 가입 → Open API 신청 → 발급받은 키를 `KEPCO_API_KEY`로 등록

키가 없는 항목은 자동으로 건너뛰고 나머지는 정상 작동하니, 급하면 나라장터 키만 먼저 넣고 시작해도 됩니다.

## 2단계. GitHub Desktop으로 저장소에 올리기

1. GitHub Desktop 설치 후 GitHub 계정으로 로그인
2. File → New repository로 새 저장소 생성
3. 압축 푸신 `emtech-biz` 폴더 안의 모든 파일/폴더(`.github` 폴더 포함)를
   방금 만든 로컬 저장소 폴더 안으로 복사해서 붙여넣기
4. GitHub Desktop에서 변경사항이 보이면 Summary 입력 → Commit to main → Push origin

## 3단계. Secrets 등록

저장소 → Settings → Secrets and variables → Actions → New repository secret으로
1단계에서 발급받은 키들을 이름 그대로 등록하세요.

## 4단계. GitHub Pages 켜기

저장소 → Settings → Pages → Source: `Deploy from a branch` → Branch: `main`, 폴더: `/docs` → Save

## 5단계. 첫 실행

저장소 → Actions → "매일 입찰공고 수집" → Run workflow

몇 분 뒤 `https://<내아이디>.github.io/<저장소이름>/` 주소에서 대시보드를 확인할 수 있습니다.
이후로는 매일 오전 8시(KST)에 자동으로 갱신됩니다.

---

## 폴더 구조

```
emtech-biz/
├── config.py                    # 검색 조건, 지역 판정 기준, 조회기간 설정
├── main.py                      # 전체 실행 (수집 → 낙찰결과 병합 → 대시보드 생성)
├── generate_dashboard.py        # docs/index.html 생성
├── scrapers/
│   ├── _common.py                # 공통 유틸 (기간 필터, 참가가능 판정)
│   ├── g2b.py                    # 나라장터 공고
│   ├── g2b_awards.py             # 나라장터 낙찰결과
│   ├── lh.py, d2b.py, kwater.py, kepco.py, korail.py
├── data/                        # 수집 결과 (자동 갱신)
├── docs/index.html              # 대시보드 (GitHub Pages로 배포)
└── .github/workflows/daily.yml  # 매일 자동 실행 설정
```

## 설정 바꾸고 싶을 때 (`config.py`)

- `HOME_CITY`, `HOME_PROVINCE`: 우리 회사 기준 지역 (현재 용인/경기)
- `MIN_DAYS_UNTIL_DEADLINE`, `MAX_DAYS_UNTIL_DEADLINE`: 투찰마감까지 며칠 남은 공고를 볼지 (현재 7~30일)
- `POST_DEADLINE_TRACK_DAYS`: 마감 후 결과를 며칠까지 계속 보여줄지 (현재 21일)
- `KEYWORDS`: 검색 키워드 (현재는 업종 전체 수집이라 미사용, 필요시 재활성화 가능)

## 알아두세요

- 공공데이터포털 API는 필드명이 가끔 바뀝니다. 특정 소스가 0건이면 Actions 로그에서
  에러 메시지를 확인해 해당 `scrapers/*.py` 파일만 손보면 됩니다.
- 참가가능 자동판정은 참고용입니다. 투찰 전 반드시 원본 공고에서 지역제한을 다시 확인하세요.
- 코레일 자체 시스템, 한국가스공사, 한국석유공사는 공개 API가 없어 자동 수집이
  안 됩니다. 대시보드 상단 바로가기 링크로 직접 확인해주세요.
