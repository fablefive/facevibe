"""Gwansang Yangban(관상가양반) MCP Server.

Korean physiognomy (face reading) tools backed by the live Gwansang Yangban
service. Reuses the live Kakao-chatbot backend endpoints:
- /ait/analyze-url (preferred) or /ait/upload-group — photo submission
- /ait/group-status — analysis polling / full report
- /category — per-category fortunes (love, investment, wealth, ...) exactly
  as served to the Kakao chatbot, persona voice included

Transport: stdio locally, Streamable HTTP (stateless, JSON) when PORT is set.
/health and / routes answer keep-alive / platform health checks.
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
# Photo submission may need to relay the image itself (download + multipart
# upload), so it gets a larger, still-bounded budget.
SUBMIT_TIMEOUT = 8
MAX_IMAGE_BYTES = 12 * 1024 * 1024

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

# Categories served by the live Kakao-chatbot /category endpoint
LIVE_CATEGORIES = {
    "love", "money", "job", "health", "ideal_type", "marriage_timing",
    "relationship_advice", "investment", "wealth_period", "career_path",
    "promotion", "change_job", "longevity", "health_advice", "exam_timing",
    "luck_fortune", "achievement",
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


# ── reading_id helpers (stateless: uid + request_id + mode in one token) ────

def _encode_reading_id(uid: str, request_id: str, mode: str) -> str:
    raw = f"{uid}:{request_id}:{mode}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_reading_id(reading_id: str):
    padded = reading_id + "=" * (-len(reading_id) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    parts = raw.split(":")
    if len(parts) == 2:  # tokens issued before the mode flag existed
        parts.append("g")
    uid, request_id, mode = parts[0], parts[1], parts[2]
    if not uid or not request_id:
        raise ValueError("malformed reading_id")
    return uid, request_id, ("p" if mode == "p" else "g")


# ── health check (keep-alive target · PlayMCP in KC 헬스체크 대응) ──────────

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "gwansang-yangban-mcp"})


@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    # 일부 플랫폼(PlayMCP in KC 등)은 컨테이너 포트의 GET / 로 헬스체크한다
    return JSONResponse({"status": "ok", "service": "gwansang-yangban-mcp", "mcp": "/mcp"})


# ── photo submission (shared by personal / group tools) ─────────────────────

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/heic": "heic", "image/heif": "heif",
}


def _submit_photo(image_url: str, mode: str) -> str:
    """Queue a photo for analysis on the live backend; returns markdown.

    Fast path: POST /ait/analyze-url (URL pass-through, no image relay).
    Fallback (current live deployment): download the image here and relay it
    as multipart to POST /ait/upload-group — both feed the same worker queue.
    """
    url = (image_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return "Error: `image_url` must be a public http(s) URL of a photo."

    uid = "mcp_" + uuid.uuid4().hex[:20]
    request_id = None

    # 1) fast path — available once the live app ships /ait/analyze-url
    try:
        r = requests.post(
            f"{API_URL}/ait/analyze-url",
            json={"image_url": url, "walletAddress": uid},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,  # gabia turns unknown routes into a 302 → 404 page
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("error"):
                return f"Error: {data['error']}"
            request_id = data.get("request_id")
    except (requests.exceptions.RequestException, ValueError):
        request_id = None

    # 2) fallback — relay the image bytes to the live /ait/upload-group
    if not request_id:
        try:
            img = requests.get(
                url, timeout=(3, 5), stream=True,
                headers={"User-Agent": "Mozilla/5.0 (GwansangYangbanMCP)"},
            )
            if img.status_code != 200:
                return (
                    f"Error: could not download the photo (HTTP {img.status_code}). "
                    "Make sure `image_url` is a publicly accessible image link."
                )
            ctype = (img.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = _EXT_BY_CONTENT_TYPE.get(ctype)
            if not ext:
                tail = url.split("?")[0].rsplit(".", 1)
                ext = tail[-1].lower() if len(tail) == 2 else ""
                if ext not in ("jpg", "jpeg", "png", "heic", "heif"):
                    return (
                        "Error: the URL does not point to a supported image "
                        "(jpg/png/heic). Use a direct photo link."
                    )
            content = b""
            for chunk in img.iter_content(chunk_size=65536):
                content += chunk
                if len(content) > MAX_IMAGE_BYTES:
                    return "Error: the photo is larger than 12MB. Use a smaller image."
            if not content:
                return "Error: the photo could not be downloaded. Use a different link."
        except requests.exceptions.RequestException as e:
            return f"Error: failed to download the photo - {e}"

        try:
            r = requests.post(
                f"{API_URL}/ait/upload-group",
                files={"file": (f"photo.{ext}", content)},
                data={"walletAddress": uid},
                timeout=SUBMIT_TIMEOUT,
            )
            if r.status_code != 200:
                return f"Error: analysis service returned status {r.status_code}. Please try again."
            data = r.json()
            if data.get("error"):
                return f"Error: {data['error']}"
            request_id = data.get("request_id")
        except requests.exceptions.Timeout:
            return "Error: the analysis service timed out. Please try again."
        except (requests.exceptions.RequestException, ValueError) as e:
            return f"Error: failed to reach the analysis service - {e}"

    if not request_id:
        return "Error: analysis service did not return a request id. Please try again."

    reading_id = _encode_reading_id(uid, request_id, mode)
    kind = "Personal" if mode == "p" else "Group"
    return (
        f"## {kind} face reading submitted 🔮\n\n"
        f"- **reading_id:** `{reading_id}`\n"
        "- Analysis takes about **15–30 seconds**.\n\n"
        "Wait, then call `get_face_reading_result` with this reading_id."
    )


# ── tool 1: personal photo ───────────────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Read Personal Face Photo",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def read_personal_face_photo(image_url: str) -> str:
    """Submits a personal (single-person) photo for AI face reading at Gwansang Yangban(관상가양반).

    Korean physiognomy analysis of one face: 40 facial attributes, one of 5
    classical face types, and persona-voiced fortunes. Analysis runs
    asynchronously (~15-30s); this returns a `reading_id` immediately. Call
    `get_face_reading_result` with it after waiting, then category tools
    (`get_love_fortune`, `get_investment_fortune`, `get_wealth_fortune`,
    `get_more_fortunes`) for deeper readings.

    Args:
        image_url: Publicly accessible URL of a photo (jpg/png) that clearly
            shows one human face.

    Returns:
        Markdown with the `reading_id` and polling instructions.
    """
    return _submit_photo(image_url, "p")


# ── tool 2: group photo ──────────────────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Read Group Face Photo",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def read_group_face_photo(image_url: str) -> str:
    """Submits a group photo for AI face reading at Gwansang Yangban(관상가양반).

    The signature feature: among everyone in the photo, the face with the best
    physiognomy is picked and marked directly on the image, and that person's
    face reading is returned. Analysis runs asynchronously (~15-30s); this
    returns a `reading_id` immediately. Call `get_face_reading_result` with it
    after waiting.

    Args:
        image_url: Publicly accessible URL of a photo (jpg/png) showing two or
            more human faces.

    Returns:
        Markdown with the `reading_id` and polling instructions.
    """
    return _submit_photo(image_url, "g")


# ── tool 3: poll the result ──────────────────────────────────────────────────

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
    When done, returns the classified face type, detected facial attributes,
    and fortune readings told in a master persona's voice. For group photos,
    includes a link to the image with the best face marked. Follow up with
    `get_love_fortune` / `get_investment_fortune` / `get_wealth_fortune` /
    `get_more_fortunes` using the same reading_id.

    Args:
        reading_id: The id returned by `read_personal_face_photo` or
            `read_group_face_photo`.

    Returns:
        Markdown face reading report, or a processing/status notice.
    """
    try:
        uid, request_id, mode = _decode_reading_id((reading_id or "").strip())
    except Exception:
        return "Error: invalid `reading_id`. Use the exact value returned by the submit tool."

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
    if mode == "g":
        lines.append("_단체사진에서 관상이 가장 좋은 얼굴을 골라 풀이했다._\n")

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
        label = "베스트 관상 얼굴 마킹 사진" if mode == "g" else "관상 포인트 마킹 사진"
        lines.append(f"- **{label}:** {image_url}")

    intro = data.get("intro")
    if intro:
        lines.append(f"\n### 총평\n{intro}")

    for f_ in data.get("fortunes", [])[:6]:
        name = CATEGORY_KO.get(f_.get("key"), f_.get("key"))
        teller = f" _(by {f_['style_name']})_" if f_.get("style_name") else ""
        lines.append(f"\n### {name}{teller}\n{f_.get('text', '')}")

    lines.append(
        "\n---\n더 보기: 같은 reading_id로 `get_love_fortune`(애정운), "
        "`get_investment_fortune`(투자운), `get_wealth_fortune`(재물운), "
        "`get_more_fortunes`(직업운·건강운·복권운 등)를 호출할 수 있다."
    )
    return "\n".join(lines)


# ── category fortunes via the live Kakao-chatbot /category endpoint ─────────

def _fetch_category_fortune(reading_id: str, category: str) -> str:
    """Calls the live /category endpoint (same one the Kakao chatbot uses)."""
    try:
        uid, _, _ = _decode_reading_id((reading_id or "").strip())
    except Exception:
        return "Error: invalid `reading_id`. Use the exact value returned by the submit tool."

    payload = {"userRequest": {"user": {"id": uid, "properties": {"botUserKey": uid}}}}
    try:
        r = requests.post(
            f"{API_URL}/category",
            json=payload,
            headers={"category": category},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return f"Error: fortune service returned status {r.status_code}. Please try again."
        data = r.json()
    except requests.exceptions.Timeout:
        return "Error: the fortune service timed out. Please try again."
    except (requests.exceptions.RequestException, ValueError) as e:
        return f"Error: failed to reach the fortune service - {e}"

    texts = [
        o["simpleText"]["text"]
        for o in (data.get("template", {}).get("outputs", []) or [])
        if isinstance(o, dict) and o.get("simpleText", {}).get("text")
    ]
    if not texts:
        return "Error: the fortune service returned an unexpected response. Please try again later."

    text = texts[0].replace("{{#mentions.user}}", "").strip()
    if "최근 분석을 토대로" not in text:
        # The backend has no completed analysis for this uid yet.
        return (
            "⏳ No completed face reading found for this reading_id yet. "
            "Make sure `get_face_reading_result` returns the report first "
            "(analysis takes ~15-30s), then call this tool again."
        )
    cat_ko = CATEGORY_KO.get(category, category)
    return f"## {cat_ko} — Gwansang Yangban(관상가양반)\n\n{text}"


# ── tool 4: love fortune (애정운) ─────────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Love Fortune",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def get_love_fortune(reading_id: str) -> str:
    """Tells the love fortune (애정운) from a completed face reading at Gwansang Yangban(관상가양반).

    Reads romance and relationship luck from the analyzed facial features,
    delivered by the love-specialist master persona — the same reading the
    live Kakao chatbot serves. Requires a finished analysis: run
    `read_personal_face_photo` or `read_group_face_photo` first and confirm
    the report via `get_face_reading_result`.

    Args:
        reading_id: The id returned by the photo submit tools.

    Returns:
        Markdown love fortune in the specialist persona's voice.
    """
    return _fetch_category_fortune(reading_id, "love")


# ── tool 5: investment fortune (투자운) ──────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Investment Fortune",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def get_investment_fortune(reading_id: str) -> str:
    """Tells the investment fortune (투자운) from a completed face reading at Gwansang Yangban(관상가양반).

    Reads investment instincts and timing from the analyzed facial features,
    in a master persona's voice — the same reading the live Kakao chatbot
    serves. For entertainment only, not financial advice. Requires a finished
    analysis from the photo submit tools.

    Args:
        reading_id: The id returned by the photo submit tools.

    Returns:
        Markdown investment fortune in a persona's voice.
    """
    return _fetch_category_fortune(reading_id, "investment")


# ── tool 6: wealth fortune (재물운) ──────────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="Wealth Fortune",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def get_wealth_fortune(reading_id: str) -> str:
    """Tells the wealth fortune (재물운) from a completed face reading at Gwansang Yangban(관상가양반).

    Reads money luck — how fortune gathers and stays — from the analyzed
    facial features, delivered by the wealth-specialist master persona, same
    as the live Kakao chatbot. For entertainment only. Requires a finished
    analysis from the photo submit tools.

    Args:
        reading_id: The id returned by the photo submit tools.

    Returns:
        Markdown wealth fortune in the specialist persona's voice.
    """
    return _fetch_category_fortune(reading_id, "money")


# ── tool 7: all other fortune categories ─────────────────────────────────────

@mcp.tool(
    annotations=ToolAnnotations(
        title="More Fortune Categories",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def get_more_fortunes(reading_id: str, category: str) -> str:
    """Tells any other fortune category from a completed face reading at Gwansang Yangban(관상가양반).

    Beyond love/investment/wealth, the live service reads 14 more categories
    from the same analyzed face. Requires a finished analysis from the photo
    submit tools.

    Args:
        reading_id: The id returned by the photo submit tools.
        category: One of: job (직업운), health (건강운), ideal_type (이상형),
            marriage_timing (결혼운), relationship_advice (연애조언),
            wealth_period (재복시기), career_path (적성운), promotion (승진운),
            change_job (이직운), longevity (장수운), health_advice (건강조언),
            exam_timing (시험운), luck_fortune (복권운), achievement (성취운).
            love/investment/money also work (same as the dedicated tools).

    Returns:
        Markdown fortune for the chosen category in a persona's voice.
    """
    cat = (category or "").strip().lower()
    if cat not in LIVE_CATEGORIES:
        return "Error: unknown category. Use one of: " + ", ".join(sorted(LIVE_CATEGORIES))
    return _fetch_category_fortune(reading_id, cat)


# ── tool 8: celebrity face reading dex ───────────────────────────────────────

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


# ── tool 9: the five face types ──────────────────────────────────────────────

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


# ── tool 10: fortune text by face type (no photo needed) ────────────────────

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

    No photo needed. Pick one of the 5 face types (see `get_face_types`) and a
    fortune category; the reading is delivered in the voice of one of 8 master
    personas. If `style` is omitted, the specialist rule applies (health →
    백강혁, love → 오은영, wealth/achievement → 진양철, others → a fixed free
    persona).

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
