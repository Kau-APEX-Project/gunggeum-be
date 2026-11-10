#!/usr/bin/env bash
# 대기 DB 처음 만들기: 기본 DB 를 통째로 복사(pg_basebackup)하고 복제 설정(-R)을 남긴 뒤 띄움.
#   사용: sudo bash deploy/db/standby/setup_standby.sh <기본DB(앱 서버) 사설 IP>
#   복제 비밀번호는 실행 중에 물어봄(화면·기록에 남지 않음). 미리 기본 DB 에 replicator 사용자와 슬롯 standby1 이 있어야 함.
#   데이터가 이미 있으면 멈춤(덮어쓰지 않음). 다시 만들려면: docker compose -f deploy/db/standby/docker-compose.yml down -v
set -euo pipefail
primary="${1:?기본 DB 사설 IP 를 인자로 주세요 (예: 10.0.141.25)}"
slot="${SLOT:-standby1}"
compose=(docker compose -f "$(cd "$(dirname "$0")" && pwd)/docker-compose.yml")

if [ -z "${REPL_PASSWORD:-}" ]; then
  read -rsp "replicator 비밀번호: " REPL_PASSWORD; echo
fi

"${compose[@]}" down 2>/dev/null || true
"${compose[@]}" run --rm --no-deps --user postgres -e PGPASSWORD="$REPL_PASSWORD" db bash -c '
  set -e
  if [ -n "$(ls -A /var/lib/postgresql/data)" ]; then
    echo "대기 DB 데이터가 이미 있음. 다시 만들려면 down -v 후 실행" >&2; exit 1
  fi
  pg_basebackup -h "$0" -U replicator -D /var/lib/postgresql/data -X stream -S "$1" -R -P
' "$primary" "$slot"
"${compose[@]}" up -d
echo "대기 DB 시작. 확인: ${compose[*]} exec db psql -U postgres -d gbg -c 'select pg_is_in_recovery();'  (t 이면 대기 중)"
