"""아키텍처 v0.2 draw.io 그림 만들기 (docs/ARCHITECTURE.md 와 같은 내용). 페이지 2장:
  1. 학기 중 구현 아키텍처 (개발 · 시연)
  2. 목표 운영 아키텍처 (3년차, B2G)

  python3 docs/diagrams/build_architecture.py   → docs/diagrams/architecture-v0.2.drawio
  PNG: draw.io -x -f png -s 1 -b 10 -p 1 -o architecture-v0.2.png architecture-v0.2.drawio  (-p 2 → architecture-target-v0.2.png)
draw.io 에서 열어 손으로 고쳐도 됨 (다시 만들면 손으로 고친 것은 덮어씀).
그리는 순서: 배경 상자 → 선 → 아이콘 (아이콘 글자가 선 위에 오도록, 글자 뒤에 배경색).
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).with_name('architecture-v0.2.drawio')
BG, FG, MUTED, RED = '#121212', '#FFFFFF', '#AAB7B8', '#FF4D4D'
SUBNET = '#161E0C'  # Public subnet 배경
AI_BG = '#0B2A27'

layers = {'back': [], 'edge': [], 'front': []}
pages: list[tuple[str, str, int, int, dict]] = []
_n = 0


def new_page(pid: str, name: str, width: int, height: int) -> None:
    global layers
    layers = {'back': [], 'edge': [], 'front': []}
    pages.append((pid, name, width, height, layers))


def nid() -> str:
    global _n
    _n += 1
    return f'c{_n}'


def value(label: str) -> str:
    """줄바꿈은 <br> (html=1), 나머지는 XML 이스케이프"""
    return escape(label.replace('\n', '<br>'), {'"': '&quot;'})


def node(label, x, y, w, h, style, layer='front'):
    i = nid()
    layers[layer].append(f'<mxCell id="{i}" value="{value(label)}" style="{style}" vertex="1" parent="1">'
                         f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return i


def edge(src, dst, label='', color=FG, dashed=False, exit=None, entry=None, points=(), bg=BG):
    i = nid()
    width = 2.5 if color == RED else 1.5
    style = (f'edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor={color};strokeWidth={width};'
             f'fontColor={FG};fontSize=11;fontStyle=1;labelBackgroundColor={bg};endArrow=classic;endSize=6;')
    if dashed:
        style += 'dashed=1;dashPattern=4 3;'
    if exit:
        style += f'exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;'
    if entry:
        style += f'entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;'
    pts = ''.join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points)
    arr = f'<Array as="points">{pts}</Array>' if pts else ''
    layers['edge'].append(f'<mxCell id="{i}" value="{value(label)}" style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
                          f'<mxGeometry relative="1" as="geometry">{arr}</mxGeometry></mxCell>')
    return i


def label_style(bg, pos='bottom'):
    where = {'bottom': 'verticalLabelPosition=bottom;verticalAlign=top;labelPosition=center;align=center;',
             'right': 'verticalLabelPosition=middle;verticalAlign=middle;labelPosition=right;align=left;spacingLeft=6;',
             'left': 'verticalLabelPosition=middle;verticalAlign=middle;labelPosition=left;align=right;spacingRight=6;'}[pos]
    return f'{where}whiteSpace=nowrap;html=1;fontColor={FG};fontSize=12;fontStyle=1;labelBackgroundColor={bg};'


def icon(label, x, y, res, fill, grad, size=64, bg=BG, pos='bottom'):
    return node(label, x, y, size, size,
                f'sketch=0;outlineConnect=0;gradientColor={grad};gradientDirection=north;fillColor={fill};strokeColor=#ffffff;'
                f'dashed=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};' + label_style(bg, pos))


def container(label, x, y, pos='bottom'):
    return node(label, x, y, 64, 44, 'sketch=0;outlineConnect=0;fillColor=#ED7100;strokeColor=none;dashed=0;aspect=fixed;'
                                     'pointerEvents=1;shape=mxgraph.aws4.container_1;' + label_style(SUBNET, pos))


def database(label, x, y, color):
    return node(label, x, y, 56, 64, f'shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;fillColor={color};strokeColor=#ffffff;'
                                     + label_style(SUBNET))


def group(label, x, y, w, h, gr_icon, stroke, fill='none', font=MUTED, dashed=False):
    return node(label, x, y, w, h,
                'outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=0;container=0;pointerEvents=0;'
                f'collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};strokeColor={stroke};'
                f'fillColor={fill};verticalAlign=top;align=left;spacingLeft=30;fontColor={font};{"dashed=1;" if dashed else "dashed=0;"}',
                layer='back')


def box(label, x, y, w, h, stroke=MUTED, fill='#1A1A1A', dashed=False, size=12, layer='front'):
    return node(label, x, y, w, h,
                f'rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};fontColor={FG};fontSize={size};'
                f'fontStyle=1;align=center;verticalAlign=middle;spacing=6;{"dashed=1;" if dashed else ""}', layer=layer)


def text(label, x, y, w, h, size=12, color=FG, bold=False, align='left'):
    return node(label, x, y, w, h, f'text;html=1;strokeColor=none;fillColor=none;align={align};verticalAlign=middle;whiteSpace=wrap;'
                                   f'fontColor={color};fontSize={size};fontStyle={1 if bold else 0};')


def person(label, x, y):
    return node(label, x, y, 40, 56, f'shape=actor;fillColor=none;strokeColor={FG};strokeWidth=2;' + label_style(BG))


def server(label, x, y):
    return node(label, x, y, 45, 78, 'shape=mxgraph.aws4.traditional_server;fillColor=#FFFFFF;strokeColor=none;aspect=fixed;'
                                     + label_style('#2A1414'))


new_page('impl-v02', '학기 중 구현 아키텍처 v0.2', 2060, 1200)

# ---------- 제목 ----------
text('현재 구현 아키텍처 v0.2 (개발 · 시연)', 650, 6, 800, 28, size=18, bold=True, align='center')
text('기준: 통합 기능명세서 v0.2 · API 명세서 v0.1 · ERD v0.1 · STT 벤치마크 v2 (2026-10-26)', 650, 32, 800, 20, size=11, color=MUTED, align='center')

# ---------- 바깥 그룹 ----------
group('AWS Cloud', 300, 60, 1430, 1120, 'group_aws_cloud', MUTED)
group('Asia Pacific (Seoul) ap-northeast-2', 340, 100, 1360, 1050, 'group_region', '#00A4A6', font='#00A4A6', dashed=True)
group('VPC', 700, 140, 620, 720, 'group_vpc2', '#8C4FFF')
node('Availability Zone A', 730, 180, 560, 660,
     f'fillColor=none;strokeColor={MUTED};dashed=1;dashPattern=1 4;verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;'
     f'fontColor={FG};fontSize=12;html=1;', layer='back')
group('Public subnet', 750, 215, 520, 610, 'group_security_group', '#7AA116', fill=SUBNET, font='#7AA116')
ec2 = group('EC2 t4g.medium (Docker Compose · 컨테이너 5개)', 770, 250, 480, 555, 'group_ec2_instance_contents', '#D86613', font='#D86613')
box('', 1360, 140, 320, 620, stroke='#0F5047', fill=AI_BG, layer='back')
box('', 1760, 330, 290, 330, stroke=RED, fill='#2A1414', dashed=True, layer='back')
box('', 770, 920, 520, 170, layer='back')
box('', 1360, 800, 320, 140, layer='back')

# ---------- 사용자 · 개발 ----------
phone = node('관광객\n(QR 모바일 웹 · PWA)', 40, 150, 46, 78,
             'shape=mxgraph.aws4.mobile_client;fillColor=#FFFFFF;strokeColor=none;aspect=fixed;' + label_style(BG))
guide = person('해설사\n발화(VAD) · 위치 · 마이크', 43, 350)
oper = person('운영자\n일정 · 공지 입력', 43, 560)
gpu = box('외부 GPU (Colab · Kaggle · 학교)\n인식 모델 학습 · TTS 합성', 10, 760, 250, 56)
gh = box('GitHub', 40, 970, 90, 44)
gha = box('GitHub Actions\n테스트 · 빌드 · 배포', 160, 962, 130, 60)

# ---------- 엣지 서비스 ----------
cf = icon('CloudFront\nHTTPS · /api · /ws', 430, 180, 'cloudfront', '#5A30B5', '#945DF2')
s3 = icon('S3\nPWA · servermap · visit\nphotos · DB 백업', 430, 440, 's3', '#277116', '#60A337')
igw = node('Internet Gateway', 620, 205, 56, 56, 'sketch=0;outlineConnect=0;fillColor=#8C4FFF;strokeColor=none;dashed=0;aspect=fixed;'
                                                 'pointerEvents=1;shape=mxgraph.aws4.internet_gateway;' + label_style(BG))

# ---------- EC2 안 ----------
nginx = container('Nginx\n라우팅 · 속도 제한 · JSON 에러', 978, 305, pos='right')
api = container('api (FastAPI · REST)\nask · card · course\nsessions · tours · notices · stats', 860, 450)
rt = container('realtime (FastAPI · WS)\n해설사·관람객 소켓\n번역 · 카드 링크 · 후처리', 1100, 450)
pg = database('PostgreSQL + pgvector\ndocs(콘텐츠 585)\n운영 테이블 7', 864, 640, '#336791')
rd = database('Redis\n세션 상태\n자막 Pub/Sub', 1104, 640, '#C6302B')

# ---------- AI · 외부 API ----------
text('AI · 외부 API', 1372, 146, 200, 20, size=12, bold=True)
openai = box('OpenAI GPT-6 Luna\n질의응답 · 의도 · 코스 LLM\n외부 API 키 (.env)', 1420, 175, 200, 70, stroke=FG, fill='#1F1F1F', size=11)
bedrock = icon('Bedrock Titan\n임베딩 (1024차원)', 1488, 280, 'bedrock', '#055F4E', '#01A88D', bg=AI_BG)
translate = icon('Translate\n자막 번역 (EN · TH)', 1488, 433, 'translate', '#055F4E', '#01A88D', bg=AI_BG)
transcribe = icon('Transcribe\n2 대안 (집 장비 없을 때)', 1488, 590, 'transcribe', '#3B3B3B', '#5C5C5C', bg=AI_BG)

# ---------- 집 장비 ----------
text('집 장비 · 사설 터널 (STT 벤치마크 v2 권장)', 1772, 336, 270, 22, size=12, bold=True)
z6 = server('1안 Z6 G4 (RTX 2070)\nWhisper turbo + 위치별 사전\n발화당 0.28초', 1882, 372)
mm = server('3안 Mac mini (M1)\nWhisper turbo (mlx)\n1안 실패 시 대체', 1882, 521)

# ---------- 외부 데이터 ----------
heritage = box('국가유산청 OpenAPI', 1780, 760, 200, 44)

# ---------- 운영 · 안전장치 ----------
text('운영 · 안전장치', 782, 926, 200, 20, size=12, bold=True)
icon('CloudWatch\n로그 · 알람', 810, 960, 'cloudwatch_2', '#B0084D', '#FF4F8B', size=56, bg='#1A1A1A')
icon('AWS Budgets\n$20 · $40 알림', 1000, 960, 'cost_explorer', '#3F8624', '#60A337', size=56, bg='#1A1A1A')
icon('IAM\n팀원별 계정 · MFA', 1190, 960, 'identity_and_access_management', '#BE0917', '#F54749', size=56, bg='#1A1A1A')

# ---------- 범례 ----------
text('범례', 1372, 806, 100, 18, size=12, bold=True)
for k, (lab, col, dash) in enumerate([('실시간 통역 경로 (해설사 음성 → 자막)', RED, False),
                                       ('요청 · 응답', FG, False),
                                       ('배치 · 백업 · 대안 경로', MUTED, True)]):
    y = 840 + k * 32
    a = node('', 1380, y, 1, 1, 'text;strokeColor=none;fillColor=none;')
    b = node('', 1440, y, 1, 1, 'text;strokeColor=none;fillColor=none;')
    edge(a, b, color=col, dashed=dash)
    text(lab, 1452, y - 11, 220, 22, size=11)

# ---------- 연결 ----------
# 관람객 · 해설사 → 입구
edge(phone, cf, 'HTTPS', exit=(1, 0.3), entry=(0, 0.3))
edge(guide, cf, '발화 · 위치 (WSS)', color=RED, exit=(1, 0.3), entry=(0, 0.7), points=[(380, 367), (380, 225)])
edge(cf, s3, '정적 파일', exit=(0.5, 1), entry=(0.5, 0))
edge(cf, igw, '/api · /ws', exit=(1, 0.5), entry=(0, 0.5))
edge(igw, nginx, '', exit=(1, 0.66), entry=(0, 0.5), points=[(940, 242), (940, 327)], bg=SUBNET)
# Nginx → 컨테이너
edge(nginx, api, '/api/*', exit=(0.25, 1), entry=(0.5, 0), points=[(994, 400), (892, 400)], bg=SUBNET)
edge(nginx, rt, '/ws/*', color=RED, exit=(0.75, 1), entry=(0.5, 0), points=[(1026, 400), (1132, 400)], bg=SUBNET)
# api
edge(api, pg, '', exit=(0.5, 1), entry=(0.5, 0))
edge(api, rd, '세션', exit=(1, 0.75), entry=(0, 0.3), points=[(1050, 483), (1050, 659)], bg=SUBNET)
edge(api, openai, 'LLM · 임베딩', exit=(0, 0.25), entry=(0, 0.5), points=[(830, 461), (830, 287), (1340, 287), (1340, 210)], bg=SUBNET)
edge(api, bedrock, '', exit=(0, 0.25), entry=(0, 0.5), points=[(830, 461), (830, 287), (1340, 287), (1340, 312)])
# realtime (빨간 경로)
edge(rt, rd, 'Pub/Sub', color=RED, exit=(0.5, 1), entry=(0.5, 0), bg=SUBNET)
edge(rt, translate, '번역 (언어 수만큼)', color=RED, exit=(1, 0.35), entry=(0, 0.5), bg=AI_BG)
edge(rt, z6, 'STT · 발화마다 (사설 터널)', color=RED, exit=(1, 0.05), entry=(0, 0.5), points=[(1300, 452), (1300, 395), (1740, 395), (1740, 411)])
edge(rt, mm, '1안 실패 시', color=RED, dashed=True, exit=(1, 0.75), entry=(0, 0.5), points=[(1320, 483), (1320, 560)], bg=AI_BG)
edge(rt, transcribe, '2 대안', color=MUTED, dashed=True, exit=(1, 0.95), entry=(0, 0.5), points=[(1300, 492), (1300, 622)], bg=AI_BG)
# 배치 · 백업 · 배포
edge(pg, s3, '매일 pg_dump', color=MUTED, dashed=True, exit=(0, 0.8), entry=(1, 0.5), points=[(560, 691), (560, 472)])
edge(gpu, s3, '모델 · 오디오 업로드', color=MUTED, dashed=True, exit=(1, 0.5), entry=(0.5, 1), points=[(462, 788)])
edge(oper, ec2, 'SSH · python -m app.cli', exit=(1, 0.5), entry=(0, 0.85), points=[(330, 588), (330, 722)])
edge(gh, gha, '', exit=(1, 0.5), entry=(0, 0.5))
edge(gha, s3, 'PWA 빌드', color=MUTED, dashed=True, exit=(0.5, 0), entry=(0.75, 1), points=[(225, 900), (478, 900)])
edge(gha, ec2, 'SSH 배포 (docker compose)', color=MUTED, dashed=True, exit=(1, 0.5), entry=(0, 0.95), points=[(720, 992), (720, 777)])
edge(heritage, pg, '문서 적재 (AI 배치 → docs.sql.gz)', color=MUTED, dashed=True, exit=(0, 0.5), entry=(1, 0.75),
     points=[(1000, 782), (1000, 688)])

# =====================================================================
# 2. 목표 운영 아키텍처 (3년차 · B2G)
# =====================================================================
new_page('target-v02', '목표 운영 아키텍처 v0.2', 2260, 1260)
APP_BG, DATA_BG = '#0C1A2A', '#1A0F24'

text('목표 운영 아키텍처 v0.2 (3년차 · B2G 위탁 운영)', 700, 6, 860, 28, size=18, bold=True, align='center')
text('구현 아키텍처와 같은 컨테이너 이미지를 관리형 서비스로 옮긴 구성 · [제안] = 팀 결정 전 (2026-10-26)', 700, 32, 860, 20, size=11,
     color=MUTED, align='center')

# 그룹
group('AWS Cloud', 290, 60, 1700, 1180, 'group_aws_cloud', MUTED)
group('Asia Pacific (Seoul) ap-northeast-2', 600, 90, 1370, 1130, 'group_region', '#00A4A6', font='#00A4A6', dashed=True)
group('VPC', 620, 130, 890, 880, 'group_vpc2', '#8C4FFF')
for x, name in ((700, 'Availability Zone A'), (1110, 'Availability Zone C')):
    node(name, x, 165, 380, 830, f'fillColor=none;strokeColor={MUTED};dashed=1;dashPattern=1 4;verticalAlign=top;align=left;'
                                 f'spacingLeft=10;spacingTop=4;fontColor={FG};fontSize=12;html=1;', layer='back')
    group('Public subnet', x + 15, 200, 350, 145, 'group_security_group', '#7AA116', fill=SUBNET, font='#7AA116')
    group('Private subnet · App', x + 15, 365, 350, 345, 'group_security_group', '#00A4A6', fill=APP_BG, font='#00A4A6')
    group('Private subnet · Data', x + 15, 730, 350, 245, 'group_security_group', '#C925D1', fill=DATA_BG, font='#C925D1')
box('', 1530, 130, 420, 640, stroke='#0F5047', fill=AI_BG, layer='back')
box('', 1530, 790, 420, 180, stroke=MUTED, layer='back')
box('', 820, 1040, 690, 170, layer='back')
box('', 1530, 1000, 420, 150, layer='back')

# 사용자 · 개발
phone2 = node('관광객\n(QR 모바일 웹 · PWA)', 40, 150, 46, 78,
              'shape=mxgraph.aws4.mobile_client;fillColor=#FFFFFF;strokeColor=none;aspect=fixed;' + label_style(BG))
guide2 = person('해설사 (구독 가이드)\n발화(VAD) · 위치 · 마이크', 43, 360)
oper2 = person('운영기관 · 운영자\n일정 · 공지 · 리포트', 43, 560)
gh2 = box('GitHub', 30, 1080, 90, 44)
gha2 = box('GitHub Actions\n테스트 · 이미지 빌드', 150, 1072, 130, 60)

# 전역 서비스 (리전 밖)
r53 = icon('Route 53\n도메인', 330, 140, 'route_53', '#4D27A8', '#A166FF', size=56)
cf2 = icon('CloudFront\nHTTPS', 460, 140, 'cloudfront', '#5A30B5', '#945DF2')
acm = icon('ACM\n인증서', 330, 300, 'certificate_manager_3', '#BE0917', '#F54749', size=56)
waf = icon('WAF\n요청 제한 (LLM · 세션 생성)', 460, 300, 'waf', '#BE0917', '#F54749')
s3b = icon('S3\nPWA · 지도 · 판정 데이터\n사진 · 모델 · 해설 오디오', 460, 480, 's3', '#277116', '#60A337')

# VPC 입구
igw2 = node('Internet Gateway', 632, 197, 56, 56, 'sketch=0;outlineConnect=0;fillColor=#8C4FFF;strokeColor=none;dashed=0;aspect=fixed;'
                                                  'pointerEvents=1;shape=mxgraph.aws4.internet_gateway;' + label_style(BG))
alb = icon('Application Load Balancer\n/api · /ws (WebSocket)', 1063, 193, 'elastic_load_balancing', '#4D27A8', '#A166FF', bg=SUBNET)
nat_style = ('sketch=0;outlineConnect=0;fillColor=#8C4FFF;strokeColor=none;dashed=0;aspect=fixed;pointerEvents=1;'
             'shape=mxgraph.aws4.nat_gateway;' + label_style(SUBNET))
node('NAT Gateway', 760, 262, 52, 52, nat_style)
node('NAT Gateway', 1390, 262, 52, 52, nat_style)


def fargate(label, x, y):
    return icon(label, x, y, 'fargate', '#D45B07', '#F78E04', size=56, bg=APP_BG)


def stt_gpu(label, x, y):
    return icon(label, x, y, 'ec2', '#D45B07', '#F78E04', size=56, bg=APP_BG)


apis, rts, stts = [], [], []
for x0 in (700, 1110):
    apis.append(fargate('API 서비스\nFargate', x0 + 40, 420))
    rts.append(fargate('실시간 통역\nFargate', x0 + 160, 420))
    stts.append(stt_gpu('STT 서비스 [제안]\nEC2 GPU · Whisper', x0 + 280, 420))
text('ECS Auto Scaling · API = 관광객 수 · 실시간 통역 = 동시 세션 수 · STT = 발화량', 735, 560, 720, 20, size=11, color='#7FD6D6',
     align='center')
text('두 AZ 모두 같은 연결 (그림은 AZ C 만 바깥 서비스와 연결)', 735, 590, 720, 20, size=11, color=MUTED, align='center')

rds_a = icon('RDS PostgreSQL\n(PostGIS · pgvector)', 760, 790, 'rds', '#2E27AD', '#527FFF', size=56, bg=DATA_BG)
ec_a = icon('ElastiCache (Redis)\nPub/Sub · 세션', 930, 790, 'elasticache', '#2E27AD', '#527FFF', size=56, bg=DATA_BG)
rds_c = icon('RDS Standby', 1170, 790, 'rds', '#2E27AD', '#527FFF', size=56, bg=DATA_BG)
ec_c = icon('ElastiCache Replica', 1340, 790, 'elasticache', '#2E27AD', '#527FFF', size=56, bg=DATA_BG)

# AI · 외부 API
text('AI · 외부 API (VPC 밖 호출은 AZ별 NAT 경유)', 1542, 136, 400, 20, size=12, bold=True)
openai2 = box('OpenAI GPT-6 Luna\n질의응답 · 의도 · 코스 LLM\n키는 Secrets Manager', 1620, 170, 240, 70, stroke=FG, fill='#1F1F1F', size=11)
bedrock2 = icon('Bedrock Titan\n임베딩', 1708, 285, 'bedrock', '#055F4E', '#01A88D', bg=AI_BG)
translate2 = icon('Translate\n자막 번역 · 용어 고정', 1708, 435, 'translate', '#055F4E', '#01A88D', bg=AI_BG)
transcribe2 = icon('Transcribe\n대안 · STT 장애 · 초과분\n(위치별 어휘 + 후처리 사전)', 1708, 600, 'transcribe', '#3B3B3B', '#5C5C5C', bg=AI_BG)

# 데이터 수집
text('데이터 수집 (서버리스)', 1542, 796, 300, 20, size=12, bold=True)
eb = icon('EventBridge\n공지 10분 · 문서 주 1회', 1580, 840, 'eventbridge', '#B0084D', '#FF4F8B', size=56, bg='#1A1A1A')
lam = icon('Lambda\n수집 · 번역 · 적재', 1790, 840, 'lambda', '#D45B07', '#F78E04', size=56, bg='#1A1A1A')
heritage2 = box('국가유산청 OpenAPI\n궁 공지', 2030, 846, 200, 54)

# 리전 안 · VPC 밖
gpu2 = icon('EC2 GPU (필요할 때만)\n모델 재학습 · TTS 합성', 660, 1080, 'ec2', '#D45B07', '#F78E04', size=56)

# 운영
text('운영 · 보안', 832, 1046, 200, 20, size=12, bold=True)
icon('CloudWatch\n로그 · 알람', 870, 1080, 'cloudwatch_2', '#B0084D', '#FF4F8B', size=56, bg='#1A1A1A')
icon('Secrets Manager\nOpenAI 키 · DB · 가이드 코드', 1030, 1080, 'secrets_manager', '#BE0917', '#F54749', size=56, bg='#1A1A1A')
ecr = icon('ECR\n컨테이너 이미지', 1210, 1080, 'ecr', '#D45B07', '#F78E04', size=56, bg='#1A1A1A')
icon('AWS Budgets\n비용 알림', 1380, 1080, 'cost_explorer', '#3F8624', '#60A337', size=56, bg='#1A1A1A')

# 범례
text('범례', 1542, 1006, 100, 18, size=12, bold=True)
for k, (lab, col, dash) in enumerate([('실시간 통역 경로 (해설사 음성 → 자막)', RED, False),
                                       ('요청 · 응답', FG, False),
                                       ('복제 · 배치 · 대안 경로', MUTED, True)]):
    y = 1040 + k * 32
    a = node('', 1550, y, 1, 1, 'text;strokeColor=none;fillColor=none;')
    b = node('', 1610, y, 1, 1, 'text;strokeColor=none;fillColor=none;')
    edge(a, b, color=col, dashed=dash)
    text(lab, 1622, y - 11, 300, 22, size=11)

# 연결 — 입구
edge(phone2, cf2, 'HTTPS', exit=(1, 0.3), entry=(0, 0.3))
edge(guide2, cf2, '발화 · 위치 (WSS)', color=RED, exit=(1, 0.3), entry=(0, 0.75), points=[(270, 377), (270, 188)])
edge(oper2, cf2, '운영 도구 (HTTPS)', exit=(1, 0.5), entry=(0, 0.9), points=[(290, 588), (290, 198)])
edge(r53, cf2, '', color=MUTED, dashed=True, exit=(1, 0.5), entry=(0, 0.5))
edge(acm, cf2, '', color=MUTED, dashed=True, exit=(0.5, 0), entry=(0.25, 1), points=[(358, 260), (476, 260)])
edge(waf, cf2, '', color=MUTED, dashed=True, exit=(0.5, 0), entry=(0.5, 1))
edge(cf2, s3b, '정적 파일', exit=(0, 0.6), entry=(0, 0.5), points=[(420, 178), (420, 512)])
edge(cf2, igw2, '/api · /ws', exit=(1, 0.5), entry=(0, 0.5), points=[(590, 172), (590, 225)])
edge(igw2, alb, '', exit=(1, 0.5), entry=(0, 0.5), bg=SUBNET)
# ALB → 서비스
for a_, r_ in zip(apis, rts):
    edge(alb, a_, '', exit=(0.5, 1), entry=(0.5, 0), bg=APP_BG)
    edge(alb, r_, '', color=RED, exit=(0.5, 1), entry=(0.5, 0), bg=APP_BG)
# AZ 안
for a_, r_, s_ in zip(apis, rts, stts):
    edge(r_, s_, '발화', color=RED, exit=(1, 0.5), entry=(0, 0.5), bg=APP_BG)
edge(rts[0], ec_a, 'Pub/Sub', color=RED, exit=(0.5, 1), entry=(0.5, 0), bg=APP_BG)
edge(rts[1], ec_a, '', color=RED, exit=(0.5, 1), entry=(1, 0.5), points=[(1298, 724), (1080, 724), (1080, 818)])
edge(apis[0], rds_a, '', exit=(0.5, 1), entry=(0.5, 0), bg=APP_BG)
edge(apis[1], rds_a, '', exit=(0.5, 1), entry=(1, 0.25), points=[(1178, 716), (900, 716), (900, 804)])
edge(rds_a, rds_c, '동기 복제 (Multi-AZ)', color=MUTED, dashed=True, exit=(1, 0.75), entry=(0, 0.75), points=[(840, 832), (840, 900), (1150, 900), (1150, 832)], bg=DATA_BG)
edge(ec_a, ec_c, '복제', color=MUTED, dashed=True, exit=(1, 0.9), entry=(0, 0.9), points=[(1010, 840), (1010, 940), (1320, 940), (1320, 840)], bg=DATA_BG)
# AZ C → 바깥 서비스
edge(apis[1], openai2, 'LLM · 임베딩', exit=(0.25, 0), entry=(0, 0.5), points=[(1164, 395), (1515, 395), (1515, 205)])
edge(apis[1], bedrock2, '', exit=(0.25, 0), entry=(0, 0.5), points=[(1164, 395), (1515, 395), (1515, 317)])
edge(rts[1], translate2, '번역', color=RED, exit=(0.75, 1), entry=(0, 0.5), points=[(1312, 530), (1525, 530), (1525, 467)], bg=AI_BG)
edge(stts[1], transcribe2, 'STT 장애 · 초과 시', color=MUTED, dashed=True, exit=(0.5, 1), entry=(0, 0.5), points=[(1418, 632)], bg=AI_BG)
# 수집 · 학습 · 배포
edge(eb, lam, '', exit=(1, 0.5), entry=(0, 0.5))
edge(lam, heritage2, '', color=MUTED, dashed=True, exit=(1, 0.5), entry=(0, 0.5))
edge(lam, rds_a, '적재', color=MUTED, dashed=True, exit=(0.5, 1), entry=(0.5, 1), points=[(1818, 990), (788, 990)])
edge(gpu2, s3b, '모델 · TTS 업로드', color=MUTED, dashed=True, exit=(0, 0.5), entry=(0.5, 1), points=[(492, 1108)])
edge(gh2, gha2, '', exit=(1, 0.5), entry=(0, 0.5))
edge(gha2, ecr, '이미지 push', color=MUTED, dashed=True, exit=(1, 0.75), entry=(0.5, 1), points=[(560, 1117), (560, 1225), (1238, 1225)])
edge(gha2, s3b, 'PWA', color=MUTED, dashed=True, exit=(0.5, 0), entry=(0, 0.85), points=[(215, 1000), (400, 1000), (400, 534)])

diagrams = ''.join(
    f'<diagram id="{pid}" name="{name}"><mxGraphModel dx="{w}" dy="{h}" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
    f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{w}" pageHeight="{h}" background="{BG}" math="0" shadow="0"><root>'
    '<mxCell id="0"/><mxCell id="1" parent="0"/>' + ''.join(ly['back'] + ly['edge'] + ly['front']) + '</root></mxGraphModel></diagram>'
    for pid, name, w, h, ly in pages)
OUT.write_text(f'<mxfile host="drawio">{diagrams}</mxfile>', encoding='utf-8')
print(OUT)
