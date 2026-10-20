"""Keep profile-stats.svg and data/history.json up to date.

    python3 scripts/profile_stats.py             # fetch GitHub data, then render
    python3 scripts/profile_stats.py --offline   # render from cached history only

Environment: GITHUB_TOKEN (provided by Actions), STAR_TOKEN (PAT; needed for
private contributions and for stargazer timestamps).

Counting model: every series is cumulative ("everything authored before this
date").  Public and private contributions are queried separately with the
`is:public` / `is:private` search qualifiers and then summed, so private work is
counted exactly once.  (The previous `repo:` scoped add-on double counted it,
because an authenticated commit/issue search already includes private repos.)
"""

import datetime
import json
import os
import sys
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
USER_TOKEN = os.environ.get("STAR_TOKEN", "")
OFFLINE = os.environ.get("PROFILE_STATS_OFFLINE") == "1" or "--offline" in sys.argv

MONTHS = 12
PACE = 2.5  # seconds between search calls (30 requests/minute limit)

SERIES = [
    ("stars", "Star", "#f2cc60"),
    ("commits", "提交", "#34d399"),
    ("prs", "PR", "#58a6ff"),
    ("issues", "Issue", "#db61a2"),
    ("repos", "公开仓库", "#a78bfa"),
]

# Only these meta keys are meaningful; everything else is legacy residue that
# used to accumulate in history.json (days, private_counts, stars_filled, ...).
META_KEYS = {"private_repos", "private_repos_error", "star_try", "counts_v3"}

TODAY = datetime.date.today()


def get(url, headers=None, retries=2, token=None):
    hdrs = dict(headers or {"User-Agent": UA})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=hdrs)
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            retryable = e.code in (403, 429) or e.code >= 500
            if not retryable or attempt >= retries:
                raise
            wait = 60 if e.code in (403, 429) else 5 * (attempt + 1)
            print(f"http {e.code}, sleeping {wait}s")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if attempt >= retries:
                raise
            time.sleep(5 * (attempt + 1))
    raise last


def graphql(query, variables, token=None):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        f"{API}/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token or USER_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def window_start(months=MONTHS):
    """First day of the month `months - 1` months ago (same window as before)."""
    y, m = TODAY.year, TODAY.month
    for _ in range(months - 1):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return datetime.date(y, m, 1)


def month_starts(start, end):
    out = []
    cur = datetime.date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = datetime.date(cur.year + cur.month // 12, cur.month % 12 + 1, 1)
    return out


def search_count(query, kind, pace=True):
    url = f"{API}/search/{kind}?q={urllib.parse.quote(query, safe='')}&per_page=1"
    try:
        data = get(url, token=USER_TOKEN or None)
        return (data or {}).get("total_count", 0)
    finally:
        if pace:
            time.sleep(PACE if USER_TOKEN else 7)


def fetch_repos():
    repos = []
    page = 1
    while True:
        url = f"{API}/users/{USER}/repos?per_page=100&page={page}&type=owner"
        data = get(url, token=USER_TOKEN or TOKEN)
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return [r for r in repos if not r.get("fork")]


def fetch_private_repos():
    if not USER_TOKEN:
        return []
    repos = []
    page = 1
    while True:
        url = (
            f"{API}/user/repos?per_page=100&page={page}"
            "&affiliation=owner,collaborator,organization_member&visibility=private"
        )
        data = get(url, token=USER_TOKEN)
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return [r for r in repos if not r.get("fork")]


def fetch_star_dates_graphql(repos):
    if not USER_TOKEN:
        return []
    q = """
    query($owner:String!, $name:String!, $cursor:String) {
      repository(owner:$owner, name:$name) {
        stargazers(first:100, after:$cursor, orderBy:{field:STARRED_AT, direction:ASC}) {
          edges { starredAt }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """
    dates = []
    for repo in repos:
        if not repo.get("stargazers_count"):
            continue
        cursor = None
        while True:
            try:
                data = graphql(q, {"owner": USER, "name": repo["name"], "cursor": cursor})
                st = (((data or {}).get("data") or {}).get("repository") or {}).get(
                    "stargazers"
                ) or {}
            except Exception as e:
                print("graphql failed:", repo["name"], e)
                return []
            for edge in st.get("edges", []):
                if edge.get("starredAt"):
                    dates.append(edge["starredAt"][:10])
            pi = st.get("pageInfo") or {}
            if not pi.get("hasNextPage"):
                break
            cursor = pi.get("endCursor")
    return dates


def fetch_star_dates_rest(repos):
    dates = []
    for repo in repos:
        if not repo.get("stargazers_count"):
            continue
        page = 1
        while True:
            try:
                data = get(
                    f"{API}/repos/{USER}/{repo['name']}/stargazers?per_page=100&page={page}",
                    {"User-Agent": UA, "Accept": "application/vnd.github.star+json"},
                    token=USER_TOKEN,
                )
            except Exception as e:
                print("stargazers failed:", repo["name"], e)
                return []
            if not data:
                break
            for s in data:
                if isinstance(s, dict) and s.get("starred_at"):
                    dates.append(s["starred_at"][:10])
            if len(data) < 100:
                break
            page += 1
    return dates


def refresh_star_dates(history, repos, star_total):
    """Keep stargazer timestamps in sync with the live star count.

    The dates used to be fetched once and never again, so historical star
    values froze at whatever the first successful fetch returned.  Now they are
    refetched whenever the count no longer matches (new stars, or un-stars),
    at most once per hour.
    """
    meta = history.setdefault("meta", {})
    star_dates = history.get("star_dates") or []
    if not repos or (star_dates and len(star_dates) == star_total):
        return star_dates

    hour_key = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H")
    if meta.get("star_try") == hour_key:
        return star_dates
    meta["star_try"] = hour_key

    fetched = fetch_star_dates_graphql(repos) or fetch_star_dates_rest(repos)
    if fetched:
        history["star_dates"] = fetched
        print(f"star_dates refreshed: {len(fetched)} (total {star_total})")
        return fetched
    print("star_dates unavailable, keeping cached values")
    return star_dates


def apply_stars(values, star_dates, star_total, today):
    """Recompute the star series for every stored point, not just today."""
    if star_dates:
        for iso in values:
            values[iso]["stars"] = sum(1 for d in star_dates if d < iso)
    if star_total:
        values.setdefault(today, {})["stars"] = star_total


QUERIES = (
    ("commits", "commits", "author:{user} {vis}author-date:<{iso}"),
    ("prs", "issues", "author:{user} type:pr {vis}created:<{iso}"),
    ("issues", "issues", "author:{user} type:issue {vis}created:<{iso}"),
)


def contribution_counts(iso):
    """Cumulative commits/PRs/issues authored before `iso`, public + private."""
    out = {}
    visibilities = ["is:public "] + (["is:private "] if USER_TOKEN else [])
    for key, kind, template in QUERIES:
        out[key] = sum(
            search_count(template.format(user=USER, vis=vis, iso=iso), kind)
            for vis in visibilities
        )
    return out


def collect(points, values, repo_dates, today, recompute=False):
    """Fill in the missing points; `recompute` refreshes every point once."""
    fresh = {}
    failures = 0
    for iso in points:
        if iso != today and iso in values and not recompute:
            continue
        entry = {"repos": sum(1 for d in repo_dates if d < iso)}
        if values.get(iso, {}).get("stars") is not None:
            # keep the old star value if the live one cannot be derived
            entry["stars"] = values[iso]["stars"]
        try:
            entry.update(contribution_counts(iso))
        except Exception as e:
            print("search failed for", iso, e)
            failures += 1
            continue
        fresh[iso] = entry
        print(iso, entry)
    return fresh, failures


def sanitize(history):
    """Drop legacy keys (days, private_counts_v2, stars_filled, ...)."""
    history.pop("days", None)
    meta = history.get("meta") or {}
    history["meta"] = {k: v for k, v in meta.items() if k in META_KEYS}
    return history


def fmt(n):
    return f"{n:,}"


def render(points, values, private_repos=None):
    W, H = 860, 420
    L = 36
    top = 100
    row_h = 60
    sx0, sx1 = 330, W - 36
    sh = 28

    rows = []
    for i, (key, label, color) in enumerate(SERIES):
        vals = [values.get(p, {}).get(key) for p in points]
        known = [v for v in vals if v is not None]
        cur = known[-1] if known else 0
        y0 = top + i * row_h

        vmax = max(known + [1])
        n = max(len(vals) - 1, 1)

        def px(j):
            return sx0 + (sx1 - sx0) * j / n

        def py(v):
            return y0 + sh - sh * (v / vmax)

        seen = [(j, v) for j, v in enumerate(vals) if v is not None]
        pts = " ".join(f"{px(j):.1f},{py(v):.1f}" for j, v in seen)
        area = ""
        if seen:
            area = (
                f"M {px(seen[0][0]):.1f},{y0 + sh} L "
                + " L ".join(f"{px(j):.1f},{py(v):.1f}" for j, v in seen)
                + f" L {px(seen[-1][0]):.1f},{y0 + sh} Z"
            )

        delta_label = "自今日起记录"
        if len(seen) > 1:
            first = datetime.date.fromisoformat(points[seen[0][0]])
            last = datetime.date.fromisoformat(points[seen[-1][0]])
            months = max(1, round((last - first).days / 30.44))
            delta_label = f"近 {months} 个月 {known[-1] - known[0]:+,}"

        rows.append(
            f'<text x="{L}" y="{y0 + 8}" fill="#c9d1d9" font-size="12" '
            f'font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">{label}</text>'
            f'<text x="{L}" y="{y0 + 34}" fill="{color}" font-size="20" font-weight="700" '
            f'font-family="ui-monospace, SFMono-Regular, Menlo, monospace">{fmt(cur)}</text>'
            f'<text x="{L + 76}" y="{y0 + 34}" fill="#6e7681" font-size="10">'
            f"{delta_label}</text>"
            f'<path d="{area}" fill="{color}" fill-opacity="0.12"/>'
            + (
                f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
                if len(seen) > 1
                else (
                    f'<circle cx="{px(seen[0][0]):.1f}" cy="{py(seen[0][1]):.1f}" r="3.5" fill="{color}"/>'
                    if seen
                    else ""
                )
            )
        )

    subtitle = "近 12 个月 · 累计值 · 每小时同步"
    if private_repos:
        subtitle = f"近 12 个月 · 累计值 · 含 {private_repos} 个私有仓库 · 每小时同步"

    xlabels = (
        f'<text x="{sx0}" y="{top + 5 * row_h + 8}" fill="#6e7681" font-size="10">'
        f"{points[0][5:]}</text>"
        f'<text x="{sx1}" y="{top + 5 * row_h + 8}" fill="#6e7681" font-size="10" '
        f'text-anchor="end">{points[-1][5:]}</text>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" fill="#0d1117" stroke="#30363d"/>
  <text x="{L}" y="40" fill="#e6edf3" font-size="20" font-weight="700"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">GitHub 增长</text>
  <text x="{L}" y="62" fill="#6e7681" font-size="11"
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">{subtitle}</text>
  {''.join(rows)}
  {xlabels}
</svg>
'''


def main():
    today = TODAY.isoformat()
    start = window_start()

    history = {"points": {}, "meta": {}}
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY, encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            print("history unreadable, starting fresh:", e)
    sanitize(history)
    values = history.setdefault("points", {})

    # keep data/history.json bounded to the 12 month window
    for iso in [k for k in values if k < start.isoformat()]:
        values.pop(iso, None)

    if not OFFLINE:
        try:
            repos = fetch_repos()
        except Exception as e:
            print("repos failed:", e)
            repos = []

        if repos:
            repo_dates = [r["created_at"][:10] for r in repos if not r.get("private")]
            star_total = sum(r.get("stargazers_count", 0) for r in repos)
            try:
                private_names = [r["full_name"] for r in fetch_private_repos()]
                history["meta"]["private_repos"] = len(private_names)
                history["meta"].pop("private_repos_error", None)
            except Exception as e:
                print("private repos failed:", e)
                history["meta"]["private_repos_error"] = str(e)[:120]

            star_dates = refresh_star_dates(history, repos, star_total)

            # one-off migration: recount every stored point, because the old
            # repo-scoped queries double counted private contributions.  Without
            # a PAT we cannot see private contributions, so wait for one instead
            # of baking in public-only numbers.
            recompute = not history["meta"].get("counts_v3")
            if recompute and not USER_TOKEN:
                print("STAR_TOKEN missing: skipping the one-off recount")
                recompute = False
            points = [d.isoformat() for d in month_starts(start, TODAY)] + [today]
            if recompute:
                points += list(values)  # stale daily points too
            fresh, failures = collect(
                sorted(set(points)), values, repo_dates, today, recompute
            )
            values.update(fresh)
            apply_stars(values, star_dates, star_total, today)
            if recompute:
                if failures:
                    print(f"recount incomplete ({failures} points), will retry")
                else:
                    history["meta"]["counts_v3"] = True
                    print("recount complete")

    os.makedirs("data", exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1, sort_keys=True)

    points = sorted(p for p in values if p >= start.isoformat())
    if today not in points:
        points.append(today)
    svg = render(points, values, history["meta"].get("private_repos"))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
