# jogumantime

Jira, Confluence, Figma에 흩어진 업무 알림을 **슬랙 DM 하나로 통합**하는 봇입니다.
우선순위를 자동 분류해서 긴급한 건 즉시, 나머지는 모아서 전달합니다.

## 주요 기능

- **알림 통합** — Jira(이슈 댓글/멘션), Confluence(페이지 댓글/멘션), Figma(디자인 댓글/멘션)을 3분 간격 폴링하여 DM으로 전달
- **우선순위 자동 분류** — 채널 가중치 + 키워드 가중치(긴급, blocker, 장애 등)로 스코어링 → URGENT/HIGH는 즉시 알림, MEDIUM/LOW는 10분 배치
- **일일 브리핑** — 평일 오전 7:30, 오늘의 할 일과 알림 요약을 DM으로 발송
- **주간 리포트** — 매주 목요일 18:00, 한 주간 알림/업무 현황 리포트 발송
- **슬래시 명령어** — `/briefing`, `/schedule`, `/priority`, `/report`

## 기술 스택

- Python (Slack Bolt + FastAPI + APScheduler)
- SQLite
- Slack Socket Mode

## 프로젝트 구조

```
work-bot/
├── app/
│   ├── main.py                    # 진입점 (Bot + API + Scheduler 단일 프로세스)
│   ├── slack_bot/                 # 슬랙 봇 (이벤트, 명령어, Block Kit UI, DM)
│   ├── core/                      # 핵심 로직 (알림, 우선순위, 브리핑, 주간리포트, 스케줄러)
│   ├── integrations/              # 외부 연동 (Jira, Confluence, Figma, Google Calendar, Claude AI)
│   ├── db/                        # DB 모델, CRUD
│   └── api/                       # FastAPI 라우트
├── config.yaml                    # 우선순위 규칙, 스케줄, 폴링 설정
├── pyproject.toml
└── .env                           # 환경 변수 (Git 제외)
```

## 설치 및 실행

### 1. 의존성 설치

```bash
cd work-bot
pip install -e ".[dev]"
```

### 2. 환경 변수 설정

`.env.example`을 복사하여 `.env`를 만들고 토큰을 입력합니다.

```bash
cp .env.example .env
```

필수 항목:
- `SLACK_BOT_TOKEN` — Slack Bot Token (xoxb-)
- `SLACK_APP_TOKEN` — Slack App-Level Token (xapp-)
- `SLACK_USER_ID` — 알림 받을 사용자 ID

선택 항목:
- `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, `ATLASSIAN_DOMAIN` — Jira/Confluence 연동
- `FIGMA_API_TOKEN` — Figma 연동

### 3. 실행

```bash
python3 -m app.main
```

## 설정

`config.yaml`에서 코드 수정 없이 아래 항목을 조정할 수 있습니다:

- 채널별/키워드별 우선순위 가중치
- 우선순위 임계값 (URGENT/HIGH/MEDIUM/LOW)
- 브리핑/배치/주간리포트 스케줄
- 폴링 간격
- Figma 파일, Confluence 제외 페이지 등
