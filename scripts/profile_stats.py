import datetime
import json
import math
import os
import re
import urllib.request

USER = "shi-YangYang"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HISTORY = "data/history.json"
OUT = "profile-stats.svg"
WINDOW = 30
HITS_URL = (
    f"https://hits.sh/github.com/{USER}.svg"
    "?label=visitors&color=34d399&style=flat-square"
)


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def fetch_followers():
    try:
        data = json.loads(
            get(
                f"https://api.github.com/users/{USER}",
                {
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": USER,
                },
            )
        )
        return data.get("followers")
    except Exception as e:
        print("user api failed:", e)
    return None


def fetch_hits():
    try:
        svg = get(HITS_URL)
        m = re.search(r'aria-label="visitors:\s*([\d,]+)"', svg)
        if not m:
            m = re.search(r">([\d,]+)</text>", svg)
        if m:
            return int(m.group(1).replace(",", ""))
    except Exception as e:
        print("hits.sh failed:", e)
    return None


def load_history():
    if os.path.exists(HISTORY):
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    return {"days": {}}


def collect(hist):
    days = hist.setdefault("days", {})
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    entry = days.get(today, {})

    followers = fetch_followers()
    if followers is not None:
        entry["followers"] = followers

    hits = fetch_hits()
    if hits is not None:
        entry["hits"] = hits

    if entry:
        days[today] = entry


def nice_max(v):
    if v <= 5:
        return 5
    mag = 10 ** int(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * mag:
            return int(m * mag)
    return int(10 * mag)


def fmt(n):
    return f"{n:,}"


def render(hist):
    days = hist.get("days", {})
    dates = sorted(days)[-WINDOW:]
    followers = [days[d].get("followers") for d in dates]
    hits = [days[d].get("hits") for d in dates]

    latest_hits = next((h for h in reversed(hits) if h is not None), 0)
    latest_followers = next((f for f in reversed(followers) if f is not None), 0)
    start = dates[0] if dates else datetime.date.today().isoformat()

    W, H = 860, 320
    L, R, T, B = 56, 28, 108, 44
    pw, ph = W - L - R, H - T - B
    series = [v for v in hits + followers if v is not None]
    ymax = nice_max(max(series + [1]))

    def x(i):
        if len(dates) <= 1:
            return L + pw / 2
        return L + pw * i / (len(dates) - 1)

    def y(v):
        return T + ph * (1 - v / ymax)

    def polyline(values, color, width, dash=None, fill=None):
        pts = [
            (x(i), y(v)) for i, v in enumerate(values) if v is not None
        ]
        if not pts:
            return ""
        attr = f'fill="none" stroke="{color}" stroke-width="{width}"'
        if dash:
            attr += f' stroke-dasharray="{dash}"'
        if len(pts) == 1:
            return f'<circle cx="{pts[0][0]:.1f}" cy="{pts[0][1]:.1f}" r="{width + 1.5}" fill="{color}"/>'
        line = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        out = f'<polyline points="{line}" {attr} stroke-linejoin="round" stroke-linecap="round"/>'
        if fill:
            area = (
                f"M {pts[0][0]:.1f},{T + ph} L "
                + " L ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
                + f" L {pts[-1][0]:.1f},{T + ph} Z"
            )
            out = f'<path d="{area}" fill="{fill}"/>' + out
        return out

    grid = []
    for k in range(5):
        gy = T + ph * k / 4
        val = ymax - ymax * k / 4
        grid.append(
            f'<line x1="{L}" y1="{gy:.1f}" x2="{W - R}" y2="{gy:.1f}" '
            f'stroke="#21262d" stroke-width="1" stroke-dasharray="3 4"/>'
            f'<text x="{L - 10}" y="{gy + 4:.1f}" fill="#6e7681" font-size="10" '
            f'text-anchor="end">{int(val)}</text>'
        )

    step = max(1, (len(dates) - 1) // 5)
    xlabels = [
        f'<text x="{x(i):.1f}" y="{T + ph + 20}" fill="#6e7681" font-size="10" '
        f'text-anchor="middle">{dates[i][5:]}</text>'
        for i in range(0, len(dates), step)
    ]

    stats = [
        ("累计访问", fmt(latest_hits)),
        ("关注者", fmt(latest_followers)),
        ("记录天数", f"{len(days)} 天"),
    ]
    sx = W - R
    blocks = []
    for label, value in reversed(stats):
        blocks.append(
            f'<text x="{sx}" y="36" fill="#8b949e" font-size="11" text-anchor="end">{label}</text>'
            f'<text x="{sx}" y="62" fill="#34d399" font-size="20" font-weight="600" '
            f'text-anchor="end" font-family="ui-monospace, SFMono-Regular, Menlo, monospace">{value}</text>'
        )
        sx -= 120

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#34d399" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#34d399" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" fill="#0d1117" stroke="#30363d"/>
  <text x="{L - 32}" y="40" fill="#e6edf3" font-size="20" font-weight="700"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">访问统计</text>
  <text x="{L - 32}" y="64" fill="#6e7681" font-size="11"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">自 {start} 起每日记录 · 近 {len(dates)} 天</text>
  {''.join(blocks)}
  {''.join(grid)}
  {polyline(followers, "#8b949e", 1.5, dash="4 3")}
  {polyline(hits, "#34d399", 2.2, fill="url(#area)")}
  {''.join(xlabels)}
  <circle cx="{L - 32}" cy="{H - 18}" r="4" fill="#34d399"/>
  <text x="{L - 22}" y="{H - 14}" fill="#8b949e" font-size="11"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">累计访问</text>
  <circle cx="{L + 32}" cy="{H - 18}" r="4" fill="#8b949e"/>
  <text x="{L + 42}" y="{H - 14}" fill="#8b949e" font-size="11"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">关注者</text>
</svg>
'''
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {OUT}: {len(dates)} days, hits={latest_hits}, followers={latest_followers}")


def main():
    hist = load_history()
    collect(hist)
    os.makedirs("data", exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1, sort_keys=True)
    render(hist)


if __name__ == "__main__":
    main()
