#!/usr/bin/env bash
# 앱 서버 배포: develop 에 들어간 커밋 하나로 api·realtime·nginx 만 다시 띄움 (db·redis 는 건드리지 않음).
#   GitHub Actions(deploy.yml) 가 SSM 문서 gunggeum-deploy 로 실행. 손으로: sudo bash deploy/app/deploy.sh <커밋 40자>
#   새 버전이 /api/health 에서 그 커밋으로 응답하지 않으면 직전 커밋으로 되돌리고 실패로 끝남.
set -euo pipefail

REPO="${GUNGGEUM_REPO:-/opt/gunggeum-be}"
BRANCH="${DEPLOY_BRANCH:-develop}"
TRIES="${HEALTH_TRIES:-40}"
WAIT="${HEALTH_WAIT:-3}"

g() { git -c safe.directory="$REPO" -C "$REPO" "$@"; }

start() {  # $1 커밋: 그 커밋으로 빌드하고 다시 띄움
  # if 안에서 부르면 set -e 가 꺼지므로 && 로 이어 한 단계라도 실패하면 멈춤
  # 설정 파일은 새 파일로 바뀌고 api 주소도 바뀌므로 nginx 는 항상 새로 만듦
  export GIT_SHA="$1"
  g checkout -q --detach "$1" &&
    docker compose build api realtime &&
    docker compose up -d --no-deps api realtime &&
    docker compose up -d --no-deps --force-recreate nginx
}

healthy() {  # $1 커밋: /api/health 의 version 이 그 커밋이 될 때까지 기다림
  local i
  for ((i = 0; i < TRIES; i++)); do
    if curl -fsS -m 5 "http://127.0.0.1:${port}/api/health" 2>/dev/null | grep -q "\"$1\""; then return 0; fi
    sleep "$WAIT"
  done
  return 1
}

main() {  # 배포 중에 이 파일이 바뀌어도 되게 함수로 감싸 다 읽고 시작
  local sha="${1:-}" prev
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "커밋 40자가 필요함" >&2; exit 2; }
  cd "$REPO"
  exec 9>"${LOCK_FILE:-/var/lock/gunggeum-deploy.lock}"
  flock -n 9 || { echo "다른 배포가 진행 중" >&2; exit 3; }
  g diff --quiet HEAD || { echo "서버에서 손으로 고친 파일이 있어 멈춤 (git status 확인)" >&2; exit 4; }
  g fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
  g merge-base --is-ancestor "$sha" "refs/remotes/origin/$BRANCH" || { echo "$BRANCH 에 없는 커밋: $sha" >&2; exit 5; }
  port="$( { grep -E '^HTTP_PORT=' .env 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d "\"' \r")"
  port="${port:-8080}"
  prev="$(g rev-parse HEAD)"
  echo "배포: $prev -> $sha"
  if start "$sha" && healthy "$sha"; then
    echo "배포 완료: $sha"
    return 0
  fi
  echo "새 버전이 정상 응답하지 않아 되돌림: $prev" >&2
  docker compose logs --tail 30 api >&2 || true
  if start "$prev" && healthy "$prev"; then echo "되돌리기 완료: $prev" >&2; else echo "되돌리기도 실패, 직접 확인 필요" >&2; fi
  exit 1
}

main "$@"
exit
