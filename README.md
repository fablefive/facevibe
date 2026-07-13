# Gwansang Yangban(관상가양반) MCP Server

🔮 **AI Korean physiognomy (face reading) MCP server** — 라이브 서비스
[관상가양반](https://facevibe.xyz)의 관상 분석·인물도감·랭킹을 MCP 툴로 노출한다.
카카오 **PlayMCP (AGENTIC PLAYER 10)** 등록용. `reference: lolgpt-mcp` 와 동일한
Render 무료 호스팅 패턴.

- 서버명: `gwansang-yangban` (Streamable HTTP, stateless, JSON response)
- 백엔드: `https://slotdle.gabia.io` (기존 라이브 API 재사용, `FACEVIBE_API_URL`로 변경 가능)

## Tools (6)

| Tool | 설명 | RO | Destr | Idem | OpenWorld |
|---|---|---|---|---|---|
| `submit_face_reading` | 사진 URL 제출 → `reading_id` 즉시 반환 (분석은 비동기 15~30초) | ❌ | ❌ | ❌ | ✅ |
| `get_face_reading_result` | `reading_id`로 결과 폴링 → 얼굴형·특징·운세 리포트 (+베스트 얼굴 마킹 사진) | ✅ | ❌ | ✅ | ✅ |
| `get_celebrity_face_readings` | 관상 인물도감 목록/상세 (인메모리, 서버 `face_dex.json` 1시간 캐시) | ✅ | ❌ | ✅ | ❌ |
| `get_face_reading_rankings` | 동안/테토/에겐 등 9종 글로벌 랭킹 TOP 10 (60초 캐시) | ✅ | ❌ | ✅ | ✅ |
| `get_face_types` | 5가지 얼굴형(금구몰니/오룡쟁주/봉학좌수면/와우/노서하전) 설명 (정적) | ✅ | ❌ | ✅ | ❌ |
| `get_fortune_by_face_type` | 얼굴형×카테고리×페르소나(8인) 운세 텍스트 (번들 JSON) | ✅ | ❌ | ✅ | ❌ |

지연 예산: 도감/얼굴형/운세는 인메모리(<5ms), 랭킹은 캐시 HTTP, 제출/결과는
slotdle 1회 호출(timeout 2.5s) → PlayMCP 요건(평균 100ms / p99 3,000ms) 충족 설계.

## 사전 조건 (백엔드)

`faceVibe/application.py` 에 **추가된** `POST /ait/analyze-url` 엔드포인트가 가비아에
배포되어 있어야 `submit_face_reading` 이 동작한다 (나머지 5개 툴은 기존 배포만으로 동작).

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
# → Tools 6개, annotations 5종, 각 툴 호출 확인
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
1) submit_face_reading(image_url="https://.../face.jpg")
   → reading_id: `bWNwX2...`
2) (15~30초 대기)
3) get_face_reading_result(reading_id="bWNwX2...")
   → 얼굴형·주요 특징·페르소나 운세 리포트
```

## Disclaimer

Face readings are for entertainment purposes only. 관상 풀이는 재미를 위한
콘텐츠이며 의학적·법률적·투자 조언이 아닙니다.
