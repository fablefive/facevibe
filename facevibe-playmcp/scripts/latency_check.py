"""PlayMCP 응답속도 요건(평균 100ms / p99 3,000ms) 실측 스크립트.

사용법:
    python scripts/latency_check.py http://localhost:8000/mcp
    python scripts/latency_check.py https://<your-app>.onrender.com/mcp

각 툴을 반복 호출해 평균 / p95 / p99 를 출력한다.
콘텐츠 툴(도감/얼굴형/운세)은 30회, 네트워크 툴(랭킹/제출/결과)은 8회.
"""

import asyncio
import statistics
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SAMPLE_IMAGE = "https://slotdle.gabia.io/static/test.jpeg"

# (tool, arguments, iterations)
CALLS = [
    ("get_face_types", {}, 30),
    ("get_celebrity_face_readings", {}, 30),
    ("get_celebrity_face_readings", {"name": "안중근"}, 30),
    ("get_fortune_by_face_type", {"face_type": "금구몰니형", "category": "money"}, 30),
    ("get_face_reading_rankings", {"category": "young"}, 8),
    ("submit_face_reading", {"image_url": SAMPLE_IMAGE}, 3),
]


def pct(values, p):
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round(p / 100 * len(values)) - 1))
    return values[idx]


async def run(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"서버 툴 {len(tools.tools)}개: {[t.name for t in tools.tools]}\n")

            all_ms = []
            reading_id = None
            for name, args, n in CALLS:
                times = []
                for _ in range(n):
                    t0 = time.perf_counter()
                    result = await session.call_tool(name, args)
                    ms = (time.perf_counter() - t0) * 1000
                    times.append(ms)
                    if name == "submit_face_reading" and reading_id is None:
                        text = result.content[0].text if result.content else ""
                        if "`" in text:
                            reading_id = text.split("`")[1]
                all_ms.extend(times)
                label = f"{name}({args})" if args else name
                print(
                    f"{label:70s} n={n:3d}  avg={statistics.mean(times):7.1f}ms  "
                    f"p95={pct(times, 95):7.1f}ms  max={max(times):7.1f}ms"
                )

            if reading_id:
                times = []
                for _ in range(8):
                    t0 = time.perf_counter()
                    await session.call_tool("get_face_reading_result", {"reading_id": reading_id})
                    times.append((time.perf_counter() - t0) * 1000)
                all_ms.extend(times)
                print(
                    f"{'get_face_reading_result':70s} n=  8  avg={statistics.mean(times):7.1f}ms  "
                    f"p95={pct(times, 95):7.1f}ms  max={max(times):7.1f}ms"
                )

            avg = statistics.mean(all_ms)
            p99 = pct(all_ms, 99)
            print("\n─────────────────────────────────────────────")
            print(f"전체 {len(all_ms)}회  평균 {avg:.1f}ms  p99 {p99:.1f}ms")
            print(f"PlayMCP 요건: 평균 <100ms {'✅' if avg < 100 else '❌'}   p99 <3000ms {'✅' if p99 < 3000 else '❌'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python scripts/latency_check.py <MCP URL (…/mcp)>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
