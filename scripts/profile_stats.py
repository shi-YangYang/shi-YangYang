import datetime
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

USER = "shi-YangYang"
HISTORY = "data/history.json"
OUT = "profile-stats.svg"
API = "https://api.github.com"
UA = "profile-stats-svg"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

SERIES = [
    ("stars", "Star", "#f2cc60"),
    ("commits", "提交", "#34d399"),
    ("prs", "PR", "#58a6ff"),
    ("issues", "Issue", "#db61a2"),
    ("repos", "仓库", "#a78bfa"),
]


def get(url, headers=None, retries=2, auth=False):
    hdrs = dict(headers or {"User-Agent": UA})
    if auth and TOKEN:
        hdrs["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=hdrs)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < retries:
                print("rate limited, sleeping 60s")
                time.sleep(60)
                continue
            raise
    return None


def get_text(url, headers=None, retries=2):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < retries:
                print("rate limited, sleeping 60s")
                time.sleep(60)
                continue
            raise
    return ""


def month_points(months=12):
    today = datetime.date.today()
    points = []
    y, m = today.year, today.month
    for _ in range(months):
        points.append(datetime.date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    points.reverse()
    points.append(today)
    return points


def search_count(query, kind):
    url = f"{API}/search/{kind}?q={urllib.parse.quote(query, safe='')}&per_page=1"
    data = get(url)
    time.sleep(7)
    return (data or {}).get("total_count", 0)


def fetch_repos():
    repos = []
    page = 1
    while True:
        data = get(f"{API}/users/{USER}/repos?per_page=100&page={page}&type=owner", auth=True)
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return repos


def fetch_star_dates(repos):
    dates = []
    for repo in repos:
        if not repo.get("stargazers_count"):
            continue
        page = 1
        while True:
            try:
                data = get(
                    f"{API}/repos/{USER}/{repo['name']}/stargazers"
                    f"?per_page=100&page={page}",
                    {
                        "User-Agent": UA,
                        "Accept": "application/vnd.github.star+json",
                    },
                    auth=True,
                )
            except Exception as e:
                print("stargazers failed:", repo["name"], e)
                break
            if not data:
                break
            for s in data:
                if isinstance(s, dict) and s.get("starred_at"):
                    dates.append(s["starred_at"][:10])
            if len(data) < 100:
                break
            page += 1
    return dates


def collect(points):
    data = {}
    try:
        repos = fetch_repos()
    except Exception as e:
        print("repos failed:", e)
        return data

    star_dates = fetch_star_dates(repos)
    repo_dates = [r["created_at"][:10] for r in repos if not r.get("fork")]

    for d in points:
        iso = d.isoformat()
        try:
            prs = search_count(f"author:{USER} type:pr created:<{iso}", "issues")
            issues = search_count(f"author:{USER} type:issue created:<{iso}", "issues")
            commits = search_count(f"author:{USER} author-date:<{iso}", "commits")
        except Exception as e:
            print("search failed for", iso, e)
            continue
        data[iso] = {
            "stars": sum(1 for x in star_dates if x < iso),
            "commits": commits,
            "prs": prs,
            "issues": issues,
            "repos": sum(1 for x in repo_dates if x < iso),
        }
        print(iso, data[iso])

    return data


def fmt(n):
    return f"{n:,}"


def render(points, values):
    W, H = 860, 420
    L = 36
    top = 100
    row_h = 60
    sx0, sx1 = 330, W - 36
    sh = 28

    rows = []
    for i, (key, label, color) in enumerate(SERIES):
        vals = [values.get(p, {}).get(key, 0) for p in points]
        cur = vals[-1] if vals else 0
        first = vals[0] if vals else 0
        delta = cur - first
        y0 = top + i * row_h

        vmax = max(vals + [1])
        n = max(len(vals) - 1, 1)

        def px(j):
            return sx0 + (sx1 - sx0) * j / n

        def py(v):
            return y0 + sh - sh * (v / vmax)

        pts = " ".join(f"{px(j):.1f},{py(v):.1f}" for j, v in enumerate(vals))
        area = f"M {px(0):.1f},{y0 + sh} L " + " L ".join(
            f"{px(j):.1f},{py(v):.1f}" for j, v in enumerate(vals)
        ) + f" L {px(len(vals) - 1):.1f},{y0 + sh} Z"

        rows.append(
            f'<text x="{L}" y="{y0 + 8}" fill="#c9d1d9" font-size="12" '
            f'font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">{label}</text>'
            f'<text x="{L}" y="{y0 + 34}" fill="{color}" font-size="20" font-weight="700" '
            f'font-family="ui-monospace, SFMono-Regular, Menlo, monospace">{fmt(cur)}</text>'
            f'<text x="{L + 76}" y="{y0 + 34}" fill="#6e7681" font-size="10">'
            f'12 个月 +{fmt(delta)}</text>'
            f'<path d="{area}" fill="{color}" fill-opacity="0.12"/>'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )

    xlabels = (
        f'<text x="{sx0}" y="{top + 5 * row_h + 8}" fill="#6e7681" font-size="10">'
        f'{points[0][5:]}</text>'
        f'<text x="{sx1}" y="{top + 5 * row_h + 8}" fill="#6e7681" font-size="10" '
        f'text-anchor="end">{points[-1][5:]}</text>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" fill="#0d1117" stroke="#30363d"/>
  <text x="{L}" y="40" fill="#e6edf3" font-size="20" font-weight="700"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">GitHub 增长</text>
  <text x="{L}" y="62" fill="#6e7681" font-size="11"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">近 12 个月 · 累计值 · 每月更新</text>
  {''.join(rows)}
  {xlabels}
</svg>
'''


def main():
    points = [d.isoformat() for d in month_points(12)]

    history = {"points": {}}
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass
    values = history.setdefault("points", {})

    fresh = collect([datetime.date.fromisoformat(p) for p in points])
    if fresh:
        values.update(fresh)
        os.makedirs("data", exist_ok=True)
        with open(HISTORY, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=1, sort_keys=True)

    render(points, values)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
