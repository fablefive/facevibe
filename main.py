"""Gwansang Yangban(관상가양반) MCP Server.

Korean physiognomy (face reading) tools backed by the live Gwansang Yangban
service. Follows the same Render-friendly pattern as lolgpt-mcp:
- stdio transport locally, Streamable HTTP (stateless, JSON) when PORT is set
- /health route for keep-alive pings
"""

import base64
import hashlib
import json
import logging
import os
import sys
import time
import uuid

import requests
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base URL of the live Gwansang Yangban backend (gabia). Endpoint paths are
# appended per tool, so this must NOT include a path.
API_URL = os.getenv("FACEVIBE_API_URL", "https://slotdle.gabia.io").rstrip("/")

# PlayMCP requires avg 100ms / p99 3,000ms — keep upstream calls short and
# fail with a friendly retry message instead of hanging.
REQUEST_TIMEOUT = 2.5

PORT = int(os.getenv("PORT", "8000"))

mcp = FastMCP(
    "gwansang-yangban",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ── bundled / cached data ────────────────────────────────────────────────────

with open(os.path.join(DATA_DIR, "face_type_scenarios_ko.json"), encoding="utf-8") as f:
    FACE_TYPE_SCENARIOS = json.load(f)

with open(os.path.join(DATA_DIR, "face_dex.json"), encoding="utf-8") as f:
    _BUNDLED_DEX = json.load(f)

_dex_cache = {"ts": 0.0, "data": _BUNDLED_DEX}
_DEX_TTL = 3600  # the live server's static/face_dex.json is the single source

_rank_cache = {}
_RANK_TTL = 60


def _get_dex():
    """Latest face_dex.json from the live server, bundled copy as fallback."""
    now = time.time()
    if now - _dex_cache["ts"] > _DEX_TTL:
        try:
            r = requests.get(f"{API_URL}/static/face_dex.json", timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                # 서버본이 구버전이면 번들(v3+) 유지 — 서버 파일 갱신 시 자동 전환
                if (isinstance(data, dict) and data.get("people")
                        and int(data.get("version", 0)) >= int(_BUNDLED_DEX.get("version", 0))):
                    _dex_cache["data"] = data
        except (requests.exceptions.RequestException, ValueError):
            pass  # keep previous/bundled data
        _dex_cache["ts"] = now
    return _dex_cache["data"]


# ── domain constants (mirrors the live backend) ─────────────────────────────

STYLE_NAMES = {
    "bjw": "백종원", "oey": "오은영", "jyc": "진양철", "bkh": "백강혁",
    "ksj": "그알톤", "msd": "마석도", "orc": "오라클", "jury": "심사위원",
}
# Specialist personas fixed per fortune category (same as the live service)
CATEGORY_PERSONA = {
    "health": "bkh", "longevity": "bkh", "health_advice": "bkh", "disease_care": "bkh",
    "love": "oey", "ideal_type": "oey", "relationship_advice": "oey", "marriage_timing": "oey",
    "money": "jyc", "achievement": "jyc",
}
FREE_PERSONAS = ["bjw", "ksj", "msd", "orc", "jury"]

CATEGORY_KO = {
    "intro": "인상 총평", "love": "애정운", "money": "재물운", "job": "직업운",
    "health": "건강운", "success": "성공운", "ideal_type": "이상형",
    "marriage_timing": "결혼시기", "relationship_advice": "연애조언",
    "investment": "투자운", "wealth_period": "재복시기", "money_caution": "재물주의",
    "career_path": "직업선택", "promotion": "승진운", "change_job": "이직운",
    "longevity": "수명", "disease_care": "질병관리", "health_advice": "건강조언",
    "exam_timing": "시험시기", "luck_fortune": "복권운", "achievement": "성취운",
}

LABEL_KO = {
    "Attractive": "매력적인 인상", "Young": "동안", "Smiling": "웃상",
    "Chubby": "통통한 얼굴", "Oval_Face": "계란형 얼굴", "High_Cheekbones": "높은 광대",
    "Big_Nose": "큰 코", "Pointy_Nose": "콧날", "Big_Lips": "도톰한 입술",
    "Narrow_Eyes": "가느다란 눈", "Arched_Eyebrows": "아치형 눈썹",
    "Bushy_Eyebrows": "숯검댕이 눈썹", "Pale_Skin": "하얀 피부", "Rosy_Cheeks": "빨간 볼",
    "Bangs": "앞머리", "No_Beard": "깔끔", "Male": "테토", "Female": "에겐",
    "Bags_Under_Eyes": "다크서클", "Mouth_Slightly_Open": "헤벌레", "Blurry": "두부상",
}

RANK_CATEGORIES = {
    "young": "🐣 동안 랭킹", "teto": "🦁 테토 랭킹", "egen": "🌸 에겐 랭킹",
    "attractive": "😎 매력 랭킹", "smile": "😊 웃상 랭킹", "tofu": "🧸 두부상 랭킹",
    "puppy": "🐶 강아지상 랭킹", "cat": "🐱 고양이상 랭킹", "arab": "👳 아랍상 랭킹",
}

FACE_TYPES_MD = """## The 5 Face Types of Gwansang Yangban(관상가양반)

1. **금구몰니형 (金龜沒泥形 · Golden Turtle Sunk in Mud)**
   Full lips, rounded nose tip, a soft smiling oval face. A wealth-gathering
   face: fortune sinks in quietly and piles up like a golden turtle hidden in
   the mud. Late-blooming but lasting riches.

2. **오룡쟁주형 (五龍爭珠形 · Five Dragons Contending for the Pearl)**
   High cheekbones, a strong prominent nose, narrow focused eyes. A born
   competitor's face — thrives in turbulent times, takes the pearl that
   everyone fights over. Leadership and ambition.

3. **봉학좌수면형 (鳳鶴坐水面形 · Phoenix and Crane on Still Water)**
   A refined sharp nose line, slender face, arched eyebrows. A noble,
   elegant face bound for reputation and artistic distinction — grace that
   stands out even in a crowd.

4. **와우형 (臥牛形 · Reclining Ox)**
   Plump gentle features and a soft rounded nose. The patient ox: steady,
   trustworthy, and unshakeable. Fortune arrives through perseverance and
   never leaves once it settles.

5. **노서하전형 (老鼠下田形 · Old Rat Coming Down to the Field)**
   A keen pointed nose and quick narrow eyes. The survivor's face — sharp
   instincts, fast hands, finds the grain wherever it is hidden.
   Resourcefulness over raw strength.
"""


# ── reading_id helpers (stateless: uid + request_id packed in one token) ────

def _encode_reading_id(uid: str, request_id: str) -> str:
    raw = f"{uid}:{request_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_reading_id(reading_id: str):
    padded = reading_id + "=" * (-len(reading_id) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    uid, _, request_id = raw.partition(":")
    if not uid or not request_id:
        raise ValueError("malformed reading_id")
    return uid, request_id


# ── health check (keep-alive target · PlayMCP in KC 헬스체크 대응) ──────────

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "gwansang-yangban-mcp"})


@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    # 일부 플랫폼(PlayMCP in KC 등)은 컨테이너 포트의 GET / 로 헬스체크한다
    return JSONResponse({"status": "ok", "service": "gwansang-yangban-mcp", "mcp": "/mcp"})


# ── tool 1: submit a face reading ────────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Submit Face Reading",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def submit_face_reading(image_url: str) -> str:
    """Submits a photo for AI face reading (Korean physiognomy) at Gwansang Yangban(관상가양반).

    The photo is queued for asynchronous analysis (face detection, 40 facial
    attributes, face-type classification). Returns a `reading_id` immediately;
    analysis takes about 15-30 seconds. Call `get_face_reading_result` with
    the returned `reading_id` after waiting. In a group photo, the face with
    the best physiognomy is automatically marked.

    Args:
        image_url: Publicly accessible URL of a photo (jpg/png) that clearly
            shows one or more human faces.

    Returns:
        Markdown with the `reading_id` and polling instructions.
    """
    url = (image_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return "Error: `image_url` must be a public http(s) URL of a photo."

    uid = "mcp_" + uuid.uuid4().hex[:20]
    try:
        r = requests.post(
            f"{API_URL}/ait/analyze-url",
            json={"image_url": url, "walletAddress": uid},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return f"Error: analysis service returned status {r.status_code}. Please try again."
        try:
            data = r.json()
        except ValueError:
            return "Error: analysis service returned an unexpected response. Please try again later."
        if data.get("error"):
            return f"Error: {data['error']}"
        request_id = data.get("request_id")
        if not request_id:
            return "Error: analysis service did not return a request id. Please try again."
    except requests.exceptions.Timeout:
        return "Error: the analysis service timed out. Please try again."
    except requests.exceptions.RequestException as e:
        return f"Error: failed to reach the analysis service - {e}"

    reading_id = _encode_reading_id(uid, request_id)
    return (
        "## Face reading submitted 🔮\n\n"
        f"- **reading_id:** `{reading_id}`\n"
        "- Analysis takes about **15–30 seconds**.\n\n"
        f"Wait, then call `get_face_reading_result` with this reading_id."
    )


# ── tool 2: poll the result ──────────────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Get Face Reading Result",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def get_face_reading_result(reading_id: str) -> str:
    """Fetches the result of a face reading submitted to Gwansang Yangban(관상가양반).

    If analysis is still running, it says so — wait ~10 seconds and call again.
    When done, returns the classified face type (one of 5 classical Korean
    physiognomy types), detected facial attributes, and fortune readings
    (wealth, love, career, health...) told in the voice of a randomly assigned
    master persona. For group photos, includes a link to the image with the
    best face marked.

    Args:
        reading_id: The id returned by `submit_face_reading`.

    Returns:
        Markdown face reading report, or a processing/status notice.
    """
    try:
        uid, request_id = _decode_reading_id((reading_id or "").strip())
    except Exception:
        return "Error: invalid `reading_id`. Use the exact value returned by `submit_face_reading`."

    try:
        r = requests.get(
            f"{API_URL}/ait/group-status",
            params={"walletAddress": uid, "request_id": request_id, "lang": "ko"},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return f"Error: result service returned status {r.status_code}. Please try again."
        try:
            data = r.json()
        except ValueError:
            return "Error: result service returned an unexpected response. Please try again later."
    except requests.exceptions.Timeout:
        return "Still working — the result service is slow right now. Try again in ~10 seconds."
    except requests.exceptions.RequestException as e:
        return f"Error: failed to reach the result service - {e}"

    status = data.get("status")
    if status == "processing" or data.get("error"):
        return "⏳ Analysis in progress. Try again in about 10 seconds."
    if status == "none":
        return "Error: no reading found for this id (it may have expired). Submit the photo again."
    if status == "no_face":
        return "😅 No human face was detected in the photo. Try a clearer, front-facing photo."
    if status == "nsfw":
        return "🚫 The photo was rejected by the content filter. Please use a different photo."
    if status != "done":
        return "⏳ Analysis in progress. Try again in about 10 seconds."

    lines = ["## 관상 리포트 — Gwansang Yangban(관상가양반) 🔮\n"]

    face_type = data.get("face_type")
    if face_type:
        lines.append(f"- **얼굴형:** {face_type}")
    age = data.get("predicted_age")
    if age:
        lines.append(f"- **관상 나이:** 약 {age}세")
    style_name = data.get("style_name")
    if style_name:
        lines.append(f"- **관상가:** {style_name}")

    attrs = sorted(
        (a for a in data.get("all_attributes", []) if a.get("label") in LABEL_KO),
        key=lambda a: -float(a.get("probability", 0)),
    )[:5]
    if attrs:
        feats = ", ".join(
            f"{LABEL_KO[a['label']]} {round(float(a['probability']) * 100)}%" for a in attrs
        )
        lines.append(f"- **주요 특징:** {feats}")

    image_url = data.get("image_url")
    if image_url:
        lines.append(f"- **베스트 얼굴 마킹 사진:** {image_url}")

    intro = data.get("intro")
    if intro:
        lines.append(f"\n### 총평\n{intro}")

    for f_ in data.get("fortunes", [])[:6]:
        name = CATEGORY_KO.get(f_.get("key"), f_.get("key"))
        teller = f" _(by {f_['style_name']})_" if f_.get("style_name") else ""
        lines.append(f"\n### {name}{teller}\n{f_.get('text', '')}")

    return "\n".join(lines)


# ── tool 3: celebrity face reading dex ───────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Celebrity Face Readings",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_celebrity_face_readings(name: str = "") -> str:
    """Browses the celebrity/historical-figure face reading collection of Gwansang Yangban(관상가양반).

    Without `name`, lists every figure in the collection (Korean historical
    heroes and public figures) with their face type and physiognomy score.
    With `name` (Korean, partial match allowed — e.g. "안중근"), returns that
    figure's full reading: face type, master's overall impression, and
    per-category fortunes, told in a celebrity master persona's voice.

    Args:
        name: Optional Korean name (or part of it) of a figure in the collection.

    Returns:
        Markdown list of figures, or one figure's full face reading.
    """
    dex = _get_dex()
    people = dex.get("people", [])

    q = (name or "").strip()
    if not q:
        lines = [f"## 관상 인물도감 — Gwansang Yangban(관상가양반) ({len(people)}인)\n"]
        for p in people:
            lines.append(
                f"- **{p.get('name')}** — {p.get('title')} "
                f"({p.get('face_type') or '얼굴형 미상'} · {p.get('overall_score')}점)"
            )
        lines.append("\nCall again with `name` set to a figure's name for the full reading.")
        return "\n".join(lines)

    person = next((p for p in people if q in (p.get("name") or "")), None)
    if not person:
        names = ", ".join(p.get("name", "?") for p in people)
        return f"'{q}' is not in the collection. Available figures: {names}"

    lines = [
        f"## {person.get('name')} — {person.get('title')}\n",
        f"- **직업/시대:** {person.get('job')} ({person.get('era', '?')})",
        f"- **얼굴형:** {person.get('face_type') or '미상'}",
        f"- **관상 점수:** {person.get('overall_score')}점 — {person.get('score_comment')}",
        f"- **풀이한 관상가:** {person.get('style_name')}",
    ]
    attrs = person.get("attributes", [])[:6]
    if attrs:
        feats = ", ".join(
            f"{LABEL_KO.get(a.get('label'), a.get('label'))} {round(float(a.get('probability', 0)) * 100)}%"
            for a in attrs
        )
        lines.append(f"- **주요 특징:** {feats}")
    if person.get("intro"):
        lines.append(f"\n### 총평\n{person['intro']}")
    for f_ in person.get("fortunes", []):
        cat = CATEGORY_KO.get(f_.get("key"), f_.get("key"))
        lines.append(f"\n### {cat} ({f_.get('score')}점)\n{f_.get('text', '')}")
    return "\n".join(lines)


# ── tool 4: global rankings ──────────────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Face Reading Rankings",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def get_face_reading_rankings(category: str = "young") -> str:
    """Shows live global face-attribute rankings from Gwansang Yangban(관상가양반).

    Every analyzed user is scored per facial attribute; this returns the
    anonymized TOP 10 leaderboard and total participant count for a category.

    Args:
        category: One of: young (baby face), teto (masculine vibe),
            egen (feminine vibe), attractive, smile, tofu (soft tofu face),
            puppy (puppy look), cat (cat look), arab (bold features).

    Returns:
        Markdown TOP 10 leaderboard with scores (0-100).
    """
    cat = (category or "young").strip().lower()
    if cat not in RANK_CATEGORIES:
        return "Error: unknown category. Use one of: " + ", ".join(RANK_CATEGORIES)

    now = time.time()
    cached = _rank_cache.get(cat)
    if cached and now - cached[0] < _RANK_TTL:
        data = cached[1]
    else:
        try:
            r = requests.get(
                f"{API_URL}/ait/rank", params={"type": cat}, timeout=REQUEST_TIMEOUT
            )
            if r.status_code != 200:
                return f"Error: ranking service returned status {r.status_code}. Please try again."
            try:
                data = r.json()
            except ValueError:
                return "Error: ranking service returned an unexpected response. Please try again later."
            if data.get("error"):
                return f"Error: {data['error']}"
            _rank_cache[cat] = (now, data)
        except requests.exceptions.Timeout:
            return "Error: the ranking service timed out. Please try again."
        except requests.exceptions.RequestException as e:
            return f"Error: failed to reach the ranking service - {e}"

    lines = [
        f"## {data.get('title', RANK_CATEGORIES[cat])}",
        f"참여자 {data.get('total', 0):,}명 · Gwansang Yangban(관상가양반)\n",
    ]
    for row in (data.get("top") or [])[:10]:
        lines.append(f"{row.get('rank')}. {row.get('name')} — {row.get('score')}점")
    if not data.get("top"):
        lines.append("No participants yet.")
    return "\n".join(lines)


# ── tool 5: the five face types ──────────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="The Five Face Types",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_face_types() -> str:
    """Explains the 5 classical face types used by Gwansang Yangban(관상가양반).

    Korean physiognomy (관상) classifies faces into archetypes. This service
    uses five: 금구몰니형 (Golden Turtle), 오룡쟁주형 (Five Dragons),
    봉학좌수면형 (Phoenix & Crane), 와우형 (Reclining Ox), and 노서하전형
    (Old Rat). Each entry covers the facial features that define the type and
    the fortune it traditionally implies.

    Returns:
        Markdown guide to the five face types.
    """
    return FACE_TYPES_MD


# ── tool 6: fortune text by face type ────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Fortune by Face Type",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_fortune_by_face_type(face_type: str, category: str = "money", style: str = "") -> str:
    """Tells a fortune for a given face type in a master persona's voice, from Gwansang Yangban(관상가양반).

    Pick one of the 5 face types (see `get_face_types`) and a fortune category;
    the reading is delivered in the voice of one of 8 master personas. If
    `style` is omitted, the specialist rule applies (health → 백강혁, love →
    오은영, wealth/achievement → 진양철, others → a fixed free persona).

    Args:
        face_type: One of: 금구몰니형, 오룡쟁주형, 봉학좌수면형, 와우형, 노서하전형.
        category: One of: love, money, job, health, success, ideal_type,
            marriage_timing, relationship_advice, investment, wealth_period,
            money_caution, career_path, promotion, change_job, longevity,
            disease_care, health_advice, exam_timing, luck_fortune, achievement, intro.
        style: Optional persona code: bjw(백종원), oey(오은영), jyc(진양철),
            bkh(백강혁), ksj(그알톤), msd(마석도), orc(오라클), jury(심사위원).

    Returns:
        Markdown fortune text in the chosen persona's voice.
    """
    ft = (face_type or "").strip()
    scenario = FACE_TYPE_SCENARIOS.get(ft)
    if not isinstance(scenario, dict):
        return "Error: unknown face_type. Use one of: " + ", ".join(FACE_TYPE_SCENARIOS)

    cat = (category or "money").strip().lower()
    texts = scenario.get(cat)
    if not isinstance(texts, dict) or not texts:
        avail = ", ".join(k for k, v in scenario.items() if isinstance(v, dict) and v)
        return f"Error: no '{cat}' reading for {ft}. Available categories: {avail}"

    code = (style or "").strip().lower()
    if code and code not in STYLE_NAMES:
        return "Error: unknown style. Use one of: " + ", ".join(
            f"{k}({v})" for k, v in STYLE_NAMES.items()
        )
    if not code:
        code = CATEGORY_PERSONA.get(cat)
    if not code or code not in texts:
        # deterministic free-persona pick → same input, same fortune (idempotent)
        seed = int(hashlib.md5(f"{ft}:{cat}".encode("utf-8")).hexdigest(), 16)
        candidates = [p for p in FREE_PERSONAS if p in texts] or sorted(texts)
        code = candidates[seed % len(candidates)]

    cat_ko = CATEGORY_KO.get(cat, cat)
    return (
        f"## {ft} — {cat_ko}\n"
        f"_관상가: {STYLE_NAMES.get(code, code)}_\n\n"
        f"{texts[code]}"
    )


def main() -> None:
    try:
        if os.getenv("PORT") or os.getenv("RENDER"):
            logger.info(
                f"Starting Gwansang Yangban MCP Server (Streamable HTTP) on 0.0.0.0:{PORT} "
                f"with API URL: {API_URL}"
            )
            mcp.run(transport="streamable-http")
        else:
            logger.info(f"Starting Gwansang Yangban MCP Server (stdio) with API URL: {API_URL}")
            mcp.run()
    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
