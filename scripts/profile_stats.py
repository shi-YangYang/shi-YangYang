import datetime
import json
import math
import os
import urllib.request

USER = "shi-YangYang"
REPO = f"{USER}/{USER}"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HISTORY = "data/history.json"
OUT = "profile-stats.svg"
WINDOW = 30


def api(path):
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": USER,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_history():
    if os.path.exists(HISTORY):
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    return {"days": {}}


def collect(hist):
    days = hist.setdefault("days", {})
    try:
        user = api(f"users/{USER}")
        hist["followers"] = user.get("followers", 0)
    except Exception as e:
        print("user api failed:", e)
    try:
        traffic = api(f"repos/{REPO}/traffic/views?per=day")
        for d in traffic.get("views", []):
            days[d["timestamp"][:10]] = {
                "views": d["count"],
                "uniques": d["uniques"],
            }
    except Exception as e:
        print("traffic api failed:", e)


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
    if not dates:
        dates = [datetime.date.today().isoformat()]
    views = [days.get(d, {}).get("views", 0) for d in dates]
    uniques = [days.get(d, {}).get("uniques", 0) for d in dates]

    total_views = sum(days[d].get("views", 0) for d in days)
    total_uniques = sum(days[d].get("uniques", 0) for d in days)
    followers = hist.get("followers", 0)

    W, H = 860, 320
    L, R, T, B = 56, 28, 104, 44
    pw, ph = W - L - R, H - T - B
    ymax = nice_max(max(views + [1]))

    def x(i):
        if len(dates) == 1:
            return L + pw / 2
        return L + pw * i / (len(dates) - 1)

    def y(v):
        return T + ph * (1 - v / ymax)

    pts_v = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(views))
    pts_u = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(uniques))
    area = (
        f"M {L},{T + ph} L "
        + " L ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(views))
        + f" L {x(len(dates) - 1):.1f},{T + ph} Z"
    )

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
    xlabels = []
    for i in range(0, len(dates), step):
        d = dates[i][5:]
        xlabels.append(
            f'<text x="{x(i):.1f}" y="{T + ph + 20}" fill="#6e7681" '
            f'font-size="10" text-anchor="middle">{d}</text>'
        )

    stats = [
        ("总访问", fmt(total_views)),
        ("独立访客", fmt(total_uniques)),
        ("关注者", fmt(followers)),
        ("统计天数", f"{len(days)} 天"),
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
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">近 {len(dates)} 天 · 来自 GitHub Traffic API（UTC）</text>
  {''.join(blocks)}
  {''.join(grid)}
  <path d="{area}" fill="url(#area)"/>
  <polyline points="{pts_u}" fill="none" stroke="#8b949e" stroke-width="1.5" stroke-dasharray="4 3"/>
  <polyline points="{pts_v}" fill="none" stroke="#34d399" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
  {''.join(xlabels)}
  <circle cx="{L - 32}" cy="{H - 18}" r="4" fill="#34d399"/>
  <text x="{L - 22}" y="{H - 14}" fill="#8b949e" font-size="11"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">访问量</text>
  <circle cx="{L + 40}" cy="{H - 18}" r="4" fill="#8b949e"/>
  <text x="{L + 50}" y="{H - 14}" fill="#8b949e" font-size="11"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">独立访客</text>
</svg>
'''
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {OUT}: {len(dates)} days, {total_views} views")


def main():
    hist = load_history()
    collect(hist)
    os.makedirs("data", exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1, sort_keys=True)
    render(hist)


if __name__ == "__main__":
    main()
