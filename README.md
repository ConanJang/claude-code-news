# Claude 소식 봇

Claude Code **장애**와 **토큰/한도 리셋 소식**을 슬랙 채널에 자동 게시합니다.

## 구독 방법

게시 채널은 `.github/workflows/news.yml`의 `CHANNELS`에 명시된 곳으로 한정합니다
(의도치 않은 채널 전파 방지). 구독 추가 = 채널에 봇 초대(`/invite`) + `CHANNELS`에 채널 ID 추가.

## 어떻게 동작하나

- GitHub Actions가 30분마다 실행 (공개 repo라 무료)
- 장애: [status.claude.com](https://status.claude.com) API에서 신규 인시던트·해소 감지
- 토큰 소식: HN에서 리셋/한도 뉴스 감지 → 원문 트윗이 있으면 fxtwitter로 본문 첨부
- 중복 방지: 발행한 이벤트 ID를 `state/published.json`에 기록 (같은 소식은 한 번만)

## 운영

- 슬랙 앱: `slack-app-manifest.yml`로 생성, 봇 토큰은 repo Secrets `SLACK_BOT_TOKEN`
- 수동 실행/테스트: Actions 탭 → claude-news → Run workflow (`test` 체크 시 연결 테스트 메시지)
