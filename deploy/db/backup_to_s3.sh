#!/usr/bin/env bash
# 매일 DB 백업: 기본 DB(compose db) 를 pg_dump(-Fc) → 검사(pg_restore -l) → S3 에 올림.
#   서버(EC2 앱 서버)에서 systemd 타이머 gunggeum-db-backup.timer 가 하루 한 번 실행. 손으로: sudo bash deploy/db/backup_to_s3.sh
#   버킷: 환경 변수 BACKUP_BUCKET, 없으면 리포 .env 의 BACKUP_BUCKET. 서버 역할(gunggeum-ec2-role)로 올림(키 없음).
#   S3 경로: s3://<버킷>/daily/gbg-YYYYMMDD-HHMMSS.dump (한국 시각). 오래된 것은 버킷 수명 주기 규칙이 지움.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo"
bucket="${BACKUP_BUCKET:-$(grep -E '^BACKUP_BUCKET=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')}"
[ -n "$bucket" ] || { echo "BACKUP_BUCKET 이 없음 (.env 에 BACKUP_BUCKET=버킷이름)" >&2; exit 1; }
region="${AWS_REGION:-ap-northeast-2}"
name="gbg-$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S).dump"
tmp="$(mktemp /var/tmp/gbg-backup.XXXXXX)"
trap 'rm -f "$tmp"' EXIT

docker compose exec -T db pg_dump -U postgres -d gbg -Fc > "$tmp"
docker compose exec -T db pg_restore -l < "$tmp" > /dev/null   # 깨진 덤프면 여기서 실패 → 올리지 않음
aws s3 cp "$tmp" "s3://$bucket/daily/$name" --region "$region" --sse AES256 --only-show-errors
echo "백업 완료: s3://$bucket/daily/$name ($(du -h "$tmp" | cut -f1))"
