# DB 2중 보호 (학기 중 아키텍처 v0.3)

| 보호 | 무엇 | 대비하는 것 |
| --- | --- | --- |
| 대기 DB | AZ C 의 EC2 `gunggeum-db-standby` 가 기본 DB 를 실시간 복제 (PostgreSQL 스트리밍 복제, 비동기) | 기본 DB·앱 서버·AZ A 장애 |
| 매일 백업 | 앱 서버가 매일 04:00(KST) `pg_dump` → S3 `s3://<버킷>/daily/` | 실수로 지운 데이터 (복제는 지운 것도 그대로 복제함) |

## 파일

| 파일 | 어디서 | 하는 일 |
| --- | --- | --- |
| `../../docker-compose.aws.yml` | 앱 서버 | db 를 5432 로 열고 복제 접속 규칙(`pg_hba.conf`) 적용, WAL 보관 상한 2GB |
| `pg_hba.conf` | 앱 서버 | 이미지 기본 규칙 + `replicator` 사용자의 VPC(10.0.0.0/16) 복제 접속 |
| `backup_to_s3.sh` | 앱 서버 | 덤프 → 검사(`pg_restore -l`) → S3 업로드. 버킷은 `.env` 의 `BACKUP_BUCKET` |
| `gunggeum-db-backup.service` · `.timer` | 앱 서버 | 매일 04:00 실행 (꺼져 있었으면 켜질 때 한 번) |
| `standby/docker-compose.yml` | 대기 DB 서버 | 기본 DB 와 같은 `pgvector/pgvector:pg17` |
| `standby/setup_standby.sh` | 대기 DB 서버 | 처음 한 번 `pg_basebackup -R` 로 복사하고 띄움 |

## 1. 앱 서버 (기본 DB)

```bash
cd /opt/gunggeum-be
# .env 에 두 줄 추가
#   COMPOSE_FILE=docker-compose.yml:docker-compose.aws.yml
#   BACKUP_BUCKET=<S3 콘솔에 보이는 버킷 전체 이름, 예: gunggeum-db-backup-<계정ID>-ap-northeast-2-an>
docker compose up -d                       # db 만 다시 뜸 (몇 초 끊김)
docker compose exec -T db psql -U postgres -c "show hba_file;"     # /etc/postgresql/pg_hba.conf
```

복제 사용자 + 슬롯 (처음 한 번). 비밀번호는 `openssl rand -hex 24` 로 만들어 따로 보관하고, 기록에 남지 않게 psql 안에서 넣음:

```bash
docker compose exec db psql -U postgres -d gbg
CREATE ROLE replicator WITH REPLICATION LOGIN;
\password replicator
SELECT pg_create_physical_replication_slot('standby1');
\q
```

매일 백업 켜기:

```bash
bash deploy/db/backup_to_s3.sh             # 손으로 한 번 → "백업 완료: s3://…"
cp deploy/db/gunggeum-db-backup.service deploy/db/gunggeum-db-backup.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now gunggeum-db-backup.timer
systemctl list-timers gunggeum-db-backup.timer   # 다음 실행 시각
journalctl -u gunggeum-db-backup.service -n 20   # 지난 실행 결과
```

## 2. 대기 DB 서버

```bash
git clone … /opt/gunggeum-be && cd /opt/gunggeum-be
bash deploy/db/standby/setup_standby.sh <앱 서버 사설 IP>    # replicator 비밀번호를 물어봄
```

## 3. 확인

```bash
# 앱 서버: state=streaming 이 한 줄
docker compose exec -T db psql -U postgres -c "select client_addr, state, replay_lag from pg_stat_replication;"
# 대기 서버: t(대기 중), 585
docker compose -f deploy/db/standby/docker-compose.yml exec -T db psql -U postgres -d gbg -c "select pg_is_in_recovery();" -c "select count(*) from docs;"
```

## 4. 장애 때 승격 (수동, 목표 15분)

```bash
# 대기 서버
docker compose -f deploy/db/standby/docker-compose.yml exec -T db psql -U postgres -c "select pg_promote();"
# 앱 서버 (살아 있을 때): .env 에 DB_HOST=<대기 서버 사설 IP> 추가 후
docker compose stop db && docker compose up -d --no-deps api realtime
curl -s localhost/api/health
```

- 승격 뒤에는 매일 백업 스크립트가 앱 서버의 db 를 보므로, 기본 DB 를 다시 만들 때까지는 대기 서버에서 `pg_dump` 로 손 백업.
- 되돌리기: 앱 서버 db 볼륨을 지우고 새 대기 DB 로 다시 복제하거나, 승격된 DB 를 덤프해 복원한 뒤 `DB_HOST` 를 지움.

## 5. 백업에서 되살리기

```bash
aws s3 ls s3://$BUCKET/daily/ --region ap-northeast-2 | tail -3
aws s3 cp s3://$BUCKET/daily/gbg-YYYYMMDD-HHMMSS.dump /var/tmp/restore.dump --region ap-northeast-2
# 먼저 별도 DB 로 시험 복원
docker compose exec -T db createdb -U postgres restore_test
docker compose exec -T db pg_restore -U postgres -d restore_test < /var/tmp/restore.dump
docker compose exec -T db psql -U postgres -d restore_test -c "select count(*) from docs;"
docker compose exec -T db dropdb -U postgres restore_test
```
