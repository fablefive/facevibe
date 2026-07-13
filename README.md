# Gwansang Yangban(관상가양반) MCP Server

🔮 **"사진 한 장이면, 조선 제일 관상가가 당신 얼굴을 읽는다."**

AI Korean physiognomy (face reading) MCP server — 라이브 서비스
[관상가양반](https://facevibe.xyz)의 관상 분석 엔진과 **카카오 챗봇 엔드포인트를
그대로 재사용**해 MCP 툴 10종으로 노출한다. 카카오 **PlayMCP (AGENTIC PLAYER 10)** 출품작.

- 서버명: `gwansang-yangban` (Streamable HTTP, stateless, JSON response)
- 백엔드: `https://slotdle.gabia.io` (기존 라이브 API 재사용, `FACEVIBE_API_URL`로 변경 가능)

## Tools (10)

| Tool | 설명 | RO | Destr | Idem | OpenWorld |
|---|---|---|---|---|---|
| `read_personal_face_photo` | 개인 사진 URL 제출 → `reading_id` 즉시 반환 (분석 비동기 15~30초) | ❌ | ❌ | ❌ | ✅ |
| `read_group_face_photo` | 단체 사진 URL 제출 → 베스트 관상 얼굴을 사진에 마킹 | ❌ | ❌ | ❌ | ✅ |
| `get_face_reading_result` | `reading_id`로 결과 폴링 → 얼굴형·특징·운세 리포트 (+마킹 사진 링크) | ✅ | ❌ | ✅ | ✅ |
| `get_love_fortune` | 애정운 — 라이브 카카오 챗봇 `/category` 엔드포인트 재사용 | ✅ | ❌ | ✅ | ✅ |
| `get_investment_fortune` | 투자운 — 〃 | ✅ | ❌ | ✅ | ✅ |
| `get_wealth_fortune` | 재물운 — 〃 | ✅ | ❌ | ✅ | ✅ |
| `get_more_fortunes` | 직업운·건강운·이상형·결혼운·복권운 등 14개 카테고리 — 〃 | ✅ | ❌ | ✅ | ✅ |
| `get_celebrity_face_readings` | 관상 인물도감 목록/상세 (인메모리, 서버 `face_dex.json` 1시간 캐시) | ✅ | ❌ | ✅ | ❌ |
| `get_face_types` | 5가지 얼굴형(금구몰니/오룡쟁주/봉학좌수면/와우/노서하전) 설명 (정적) | ✅ | ❌ | ✅ | ❌ |
| `get_fortune_by_face_type` | (사진 없이) 얼굴형×카테고리×페르소나(8인) 운세 텍스트 (번들 JSON) | ✅ | ❌ | ✅ | ❌ |

지연 예산: 도감/얼굴형/운세는 인메모리(<5ms), 결과 폴링·카테고리 운세는 slotdle
1회 호출(timeout 2.5s), 사진 제출만 이미지 릴레이 예산 8s → PlayMCP 요건
(평균 100ms / p99 3,000ms)에 맞춘 설계.

## 카카오 챗봇 엔드포인트 재사용 구조

이 MCP는 별도 분석 서버 없이, 라이브 중인 카카오 챗봇 백엔드를 그대로 부른다.

| MCP 툴 | 라이브 엔드포인트 | 비고 |
|---|---|---|
| 사진 제출 | `POST /ait/analyze-url` (배포 시) → 폴백 `POST /ait/upload-group` | 폴백은 MCP 서버가 이미지를 내려받아 멀티파트 릴레이 |
| 결과 폴링 | `GET /ait/group-status` | 카카오 `/many` 플로우와 동일한 워커 큐 |
| 애정운/투자운/재물운/기타 | `POST /category` (+`category` 헤더) | 카카오 챗봇 스킬과 완전히 동일한 응답 생성 경로 |

`/ait/analyze-url`이 아직 라이브에 배포되지 않아도 **현재 라이브 배포만으로 전체
툴이 동작한다** (제출은 자동으로 `/ait/upload-group` 폴백 사용). 추후 analyze-url이
배포되면 이미지 릴레이 없는 빠른 경로로 자동 전환된다.

## 로컬 실행

```bash
pip install -r requirements.txt

# stdio 모드 (Claude Desktop 등 로컬 클라이언트)
python main.py

# Streamable HTTP 모드 — PORT 설정 시 활성화
PORT=8000 python main.py
# → MCP 엔드포인트: http://localhost:8000/mcp
# → 헬스체크:       http://localhost:8000/health
```

### MCP Inspector 검증

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP / URL: http://localhost:8000/mcp
# → Tools 10개, annotations 5종, 각 툴 호출 확인
```

### 지연 실측 (PlayMCP 요건)

```bash
python scripts/latency_check.py http://localhost:8000/mcp
python scripts/latency_check.py https://<your-app>.onrender.com/mcp   # 배포 후
```

## PlayMCP in KC 배포 (Git 소스 빌드 · 권장)

1. 이 폴더를 GitHub **public** 저장소로 push (루트에 `Dockerfile` 필수 — 이미 있음).
2. https://playmcp.kakaocloud.io → **+ 새 MCP 서버 등록 → Git 소스 빌드**
   - Git URL: `https://github.com/<계정>/facevibe-playmcp`
   - 브랜치: `main` / Dockerfile 경로: `Dockerfile` / PAT: 비움(public)
   - 환경변수·시크릿: 불필요 (필요 시 `FACEVIBE_API_URL`만)
   - 컨테이너 포트: `8000` (기본값 그대로 — Dockerfile이 8000에서 listen)
3. Status가 **Active**가 되면 상세에서 **Endpoint URL** 복사 → PlayMCP 등록에 사용.
4. MCP 서버는 계정당 최대 2개 — 기존 failed 항목은 삭제 후 등록.

> ⚠️ 빌드는 되는데 Active가 안 되고 failed면 대부분 "컨테이너가 8000 포트를 listen하지
> 않는 경우"다. 이 저장소는 Dockerfile에서 `ENV PORT=8000`을 설정해 main.py가
> Streamable HTTP 모드(0.0.0.0:8000)로 뜨고, `/`와 `/health`가 200을 반환한다.

## PlayMCP 등록 정보 (복사용)

**서비스 설명 (국문)**

> 🔮 사진 한 장이면, 조선 제일 관상가가 당신 얼굴을 읽어드립니다 — 관상가양반
>
> 얼굴 사진 URL(이미지 링크)을 건네면 AI가 40가지 얼굴 특징을 분석해 5가지 전통
> 얼굴형(금구몰니형·오룡쟁주형 등)으로 분류하고, 애정운·투자운·재물운을 비롯한
> 17가지 운세를 개성 넘치는 관상가 말투로 풀어드립니다. 단체사진을 주면 **관상이
> 가장 좋은 한 명을 사진에 직접 표시**해 돌려주는 것이 시그니처 — 모임 대화방에서
> 한 번 돌리면 멈출 수 없습니다.
>
> 사진이 없어도 즐길 거리가 가득합니다:
> · "안중근 의사 관상은 어땠어?" → 위인 관상 도감 (역사 인물 풀이)
> · "금구몰니형 재물운 알려줘" → 얼굴형별 운세를 8가지 관상가 페르소나 말투로
>
> 결과는 간결한 마크다운 요약으로 반환되어 대화 흐름을 끊지 않으며, 실서비스
> (웹·안드로이드·iOS 앱·카카오 챗봇 운영 중)와 동일한 분석 엔진·응답 경로를
> 사용합니다. 관상은 재미를 위한 콘텐츠입니다.

**Service description (EN)**

> One photo, and Joseon's finest face reader tells your fortune. Gwansang
> Yangban(관상가양반) analyzes 40 facial attributes, classifies your face into
> one of five classical Korean physiognomy types, and tells your love,
> investment, and wealth fortunes (17 categories) in the voices of eight
> master personas. Its signature trick: upload a group photo and it marks the
> person with the best face — instantly viral in any group chat. No photo?
> Browse face readings of Korean historical figures and face-type fortunes.
> Same engine and response path as the live web/Android/iOS/Kakao-chatbot
> service. For entertainment.

**대화 예시 (등록 폼 · 3개)**

1. 이 사진 관상 좀 봐줘: https://commons.wikimedia.org/wiki/Special:FilePath/Abraham%20Lincoln%20O-77%20matte%20collodion%20print.jpg
2. 방금 그 사진으로 투자운이랑 재물운도 봐줘.
3. 안중근 의사는 관상이 어땠는지 궁금해. 관상 도감에서 찾아서 풀이해줘.

## Render 배포 (무료)

1. 이 폴더를 GitHub 저장소로 push.
2. [Render](https://render.com) → **New + → Blueprint** → 저장소 선택 → 배포
   (`render.yaml` 자동 인식, 카드 불필요).
3. 엔드포인트: `https://<your-app>.onrender.com/mcp`
4. **슬립 방지**: Render 무료는 15분 무활동 시 슬립(콜드스타트 30~60초).
   - [UptimeRobot](https://uptimerobot.com) 무료 모니터에 `/health` URL을 5분 간격 등록 (권장)
   - 또는 노트북에서 `python keepalive.py https://<your-app>.onrender.com`
5. **커스텀 도메인(선택)**: Render 서비스 Settings → Custom Domain에
   `mcp.facevibe.xyz` 추가 → 가비아 DNS에 CNAME `mcp` → `<your-app>.onrender.com`
   등록. 이후 호스팅을 옮겨도 PlayMCP 등록 URL 불변.
6. 지연 기준 미달 시: Oracle Cloud Always Free 춘천 리전 ARM VM으로 이전
   (`Dockerfile` 동봉, Caddy로 HTTPS).

## PlayMCP 등록

1. https://playmcp.kakao.com 개발자 콘솔 → MCP 서버 등록
2. 식별자: `gwansang-yangban` / URL: `https://mcp.facevibe.xyz/mcp`
   (또는 `https://<your-app>.onrender.com/mcp`)
3. 서비스 설명·아이콘 등록 → 심사 제출 (AGENTIC PLAYER 10)
4. 심사 기간 동안 keep-alive 유지 필수 (콜드스타트가 p99를 깨뜨림)

## E2E 테스트 예시

```
1) read_personal_face_photo(image_url="https://.../face.jpg")   # 단체사진은 read_group_face_photo
   → reading_id: `bWNwX2...`
2) (15~30초 대기)
3) get_face_reading_result(reading_id="bWNwX2...")
   → 얼굴형·주요 특징·페르소나 운세 리포트 (+마킹 사진 링크)
4) get_love_fortune / get_investment_fortune / get_wealth_fortune (reading_id 재사용)
   → 카카오 챗봇과 동일한 카테고리별 심층 풀이
5) get_more_fortunes(reading_id, category="luck_fortune")
   → 복권운 등 14개 추가 카테고리
```

## Disclaimer

Face readings are for entertainment purposes only. 관상 풀이는 재미를 위한
콘텐츠이며 의학적·법률적·투자 조언이 아닙니다.
