# 자동 배포 (CD): GitHub Actions → SSM

develop 에 합쳐지면 테스트를 통과한 커밋을 앱 서버에 배포합니다. AWS 키와 SSH 를 쓰지 않습니다.

1. `deploy.yml` 이 `ci.yml` 테스트를 먼저 돌림
2. GitHub `production` 환경의 승인을 기다림 (승인자를 지정했을 때)
3. OIDC 로 AWS 역할을 빌려 SSM 문서 `gunggeum-deploy` 를 실행 (그 문서 말고는 실행할 수 없음)
4. 서버의 `deploy.sh` 가 api·realtime·nginx 만 다시 띄우고, `/api/health` 의 `version` 이 그 커밋인지 확인. 아니면 직전 커밋으로 되돌림

db·redis 는 건드리지 않습니다. 배포하는 동안 api·통역 연결이 잠깐 끊기므로 해설 중에는 승인하지 않습니다. DB 구조를 바꾸는 변경은 되돌리기 대상이 아닙니다.

## 준비 (처음 한 번)

| 순서 | 어디서 | 할 일 |
| --- | --- | --- |
| 1 | 앱 서버 | `/opt/gunggeum-be` 가 git 리포인지, 손으로 고친 파일이 없는지(`git status`) 확인하고 `deploy/app/deploy.sh` 가 있는 커밋으로 한 번 맞춤 |
| 2 | AWS IAM | GitHub OIDC 공급자 `token.actions.githubusercontent.com` (대상 `sts.amazonaws.com`) 추가 |
| 3 | AWS IAM | 역할 `gunggeum-github-deploy`: 신뢰 `iam-trust.json` (`sub` 의 @숫자는 GitHub 조직·리포 고유 번호, 이름이 바뀌거나 새로 만들어져도 다른 리포가 쓸 수 없음), 권한 `iam-permissions.json` (`<ACCOUNT_ID>`·`<APP_INSTANCE_ID>` 를 채움) |
| 4 | AWS SSM | `ssm-document.json` 으로 Command 문서 `gunggeum-deploy` 만들기 |
| 5 | GitHub 설정 | 환경 `production`: 승인자 지정, 배포 브랜치 `develop` 만, secret `AWS_DEPLOY_ROLE_ARN`·`APP_INSTANCE_ID` (변수로 두면 공개 로그에 보임) |
| 6 | GitHub 설정 | 리포 변수 `DEPLOY_ENABLED=1` (이때부터 배포가 켜짐. 끄려면 지움) |

## 손으로 배포·되돌리기

```bash
sudo bash /opt/gunggeum-be/deploy/app/deploy.sh <develop 에 있는 커밋 40자>
```

## 공지 자동 수집 켜기 (처음 한 번)

경복궁 공지의 제목·날짜·링크만 초안으로 저장합니다. 운영자가 `/api/admin/notice-drafts` 에서 승인한 것만 관람객에게 나옵니다.

```bash
cd /opt/gunggeum-be
docker compose exec -T api python -m app.cli collect        # 손으로 한 번 → "새 초안 N건"
cp deploy/app/gunggeum-notice-collect.service deploy/app/gunggeum-notice-collect.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now gunggeum-notice-collect.timer
journalctl -u gunggeum-notice-collect.service -n 20         # 지난 실행 결과
```

- 새 초안 메일: SNS 주제를 만들어 운영자 메일을 구독하고, 서버 역할에 그 주제만 `sns:Publish` 를 준 뒤 `.env` 에 `NOTICE_SNS_TOPIC_ARN` 을 넣음
- 사이트를 읽지 못하면 실행이 실패로 남고, 초안 목록 응답의 `collect.lastError` 에 이유가 나옴
- 끄기: `systemctl disable --now gunggeum-notice-collect.timer`
