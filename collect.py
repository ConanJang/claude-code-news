#!/usr/bin/env python3
"""Claude Code 소식 수집·게시 봇.

수집: status.claude.com 장애 인시던트 + HN에서 토큰 리셋/한도 뉴스.
게시: 봇이 초대된 모든 슬랙 채널에 chat.postMessage.
중복 방지: state/published.json에 발행한 이벤트 ID 기록.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

STATE_PATH = os.path.join(os.path.dirname(__file__), "state", "published.json")
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
KST = timezone(timedelta(hours=9))

STATUS_API = "https://status.claude.com/api/v2/incidents.json"
HN_API = (
    "https://hn.algolia.com/api/v1/search_by_date?"
    + urllib.parse.urlencode({"query": "claude", "tags": "story", "hitsPerPage": 50})
)
FXTWITTER_API = "https://api.fxtwitter.com/i/status/{id}"


def http_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"incidents": {}, "news": []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def kst(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST)
    return dt.strftime("%m/%d %H:%M")


# ---------- 수집 ----------

def collect_incidents(state):
    """새 인시던트 또는 상태 변화(해소 등)를 이벤트로 만든다."""
    events = []
    for inc in http_json(STATUS_API)["incidents"][:20]:
        prev = state["incidents"].get(inc["id"])
        cur = inc["status"]  # investigating/identified/monitoring/resolved
        if prev == cur:
            continue
        state["incidents"][inc["id"]] = cur
        if prev is None and cur == "resolved":
            continue  # 이미 끝난 과거 인시던트는 소급 게시하지 않는다
        if cur == "resolved":
            text = f":white_check_mark: *Claude 장애 해소* — {inc['name']}"
        else:
            text = (
                f":rotating_light: *Claude 장애 감지* — {inc['name']}\n"
                f"상태: {cur} · 시작 {kst(inc['created_at'])} (KST)\n"
                f"<{inc['shortlink']}|상태 페이지에서 보기>"
            )
        events.append(text)
    return events


RESET_RE = re.compile(r"reset|refund|credit", re.I)
LIMIT_RE = re.compile(r"limit|usage|quota|rate", re.I)
TWEET_RE = re.compile(r"(?:x|twitter|xcancel)\.com/[^/]+/status/(\d+)")


def tweet_text(url):
    m = TWEET_RE.search(url or "")
    if not m:
        return None
    try:
        t = http_json(FXTWITTER_API.format(id=m.group(1))).get("tweet", {})
        return t.get("text")
    except Exception:
        return None


def news_keys(hit):
    """같은 사건의 크로스포스트를 하나로 병합하는 canonical key들.

    날짜 키로 항상 묶고, 트윗 링크가 있으면 트윗 ID 키도 함께 기록한다."""
    keys = [f"reset:{hit['created_at'][:10]}"]
    m = TWEET_RE.search(hit.get("url") or "")
    if m:
        keys.append(f"tweet:{m.group(1)}")
    return keys


def collect_reset_news(state):
    """HN에서 토큰 리셋/한도 변경 뉴스를 찾는다."""
    events = []
    for hit in http_json(HN_API)["hits"]:
        title = hit.get("title") or ""
        if not (RESET_RE.search(title) and LIMIT_RE.search(title)):
            continue
        keys = news_keys(hit)
        if any(k in state["news"] for k in keys):
            continue
        state["news"] += keys
        hn_url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        text = f":gift: *Claude 토큰/한도 소식* — {title}"
        quote = tweet_text(hit.get("url"))
        if quote:
            text += f"\n> {quote}"
        if hit.get("url"):
            text += f"\n<{hit['url']}|원문>"
        text += f" · <{hn_url}|HN 논의>"
        events.append(text)
    state["news"] = state["news"][-500:]
    return events


# ---------- 슬랙 게시 ----------

def slack_api(method, **params):
    data = urllib.parse.urlencode(params).encode()
    res = http_json(
        f"https://slack.com/api/{method}",
        data=data,
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
    )
    if not res.get("ok"):
        print(f"slack {method} 실패: {res.get('error')}", file=sys.stderr)
    return res


def post_all(events):
    """게시 대상은 webhook URL(채널 고정) 우선, 없으면 CHANNELS에 명시된 채널만."""
    webhooks = [u for u in os.environ.get("SLACK_WEBHOOK_URLS", "").split(",") if u.strip()]
    if webhooks:
        for text in events:
            body = json.dumps({"text": text}).encode()
            for url in webhooks:
                req = urllib.request.Request(
                    url, data=body, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=20) as res:
                    if res.read().decode() != "ok":
                        print("webhook 게시 실패", file=sys.stderr)
        return
    channels = [c for c in os.environ.get("CHANNELS", "").split(",") if c.strip()]
    if not channels:
        sys.exit("SLACK_WEBHOOK_URLS와 CHANNELS가 모두 비어 있습니다")
    for text in events:
        for ch in channels:
            slack_api("chat.postMessage", channel=ch, text=text, unfurl_links="false")


def main():
    if not SLACK_TOKEN and not os.environ.get("SLACK_WEBHOOK_URLS"):
        sys.exit("SLACK_WEBHOOK_URLS 또는 SLACK_BOT_TOKEN이 필요합니다")
    if "--test" in sys.argv:
        post_all([":wave: Claude 소식 봇 연결 테스트입니다. 이 채널은 구독 중입니다."])
        return
    state = load_state()
    first_run = not state["incidents"] and not state["news"]
    # 리셋 감지는 로컬 statusLine 훅으로 이관(HN 경로는 ~2h 지연·부정확).
    # collect_reset_news 함수는 복구 대비 남겨두되 호출하지 않는다. 장애만 Actions가 담당.
    events = collect_incidents(state)
    save_state(state)
    if first_run:
        print(f"첫 실행: 기존 {len(events)}건은 기록만 하고 게시 생략")
        return
    print(f"신규 이벤트 {len(events)}건")
    post_all(events)


if __name__ == "__main__":
    main()
