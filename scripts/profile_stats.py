import datetime
import json
import os
import re
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

SERIES = [
    ("stars", "Star", "#f2cc60"),
    ("commits", "提交", "#34d399"),
    ("prs", "PR", "#58a6ff"),
    ("issues", "Issue", "#db61a2"),
    ("repos", "仓库", "#a78bfa"),
]


def get(url, headers=None, retries=2, auth=False, token=None):
    hdrs = dict(headers or {"User-Agent": UA})
    use = token or (TOKEN if auth else "")
    if use:
        hdrs["Authorization"] = f"Bearer {use}"
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


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        f"{API}/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {USER_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


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


def search_count(query, kind, pace=True):
    url = f"{API}/search/{kind}?q={urllib.parse.quote(query, safe='')}&per_page=1"
    data = get(url, token=USER_TOKEN or None)
    if pace:
        time.sleep(2.5 if USER_TOKEN else 7)
    return (data or {}).get("total_count", 0)


def fetch_repos():
    repos = []
    page = 1
    while True:
        if USER_TOKEN:
            url = (
                f"{API}/user/repos?per_page=100&page={page}"
                "&affiliation=owner&visibility=all"
            )
            data = get(url, token=USER_TOKEN)
        else:
            url = f"{API}/users/{USER}/repos?per_page=100&page={page}&type=owner"
            data = get(url, auth=True)
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    seen = set()
    out = []
    for r in repos:
        key = r.get("full_name") or r.get("name")
        if r.get("fork") or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


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
                data = graphql(
                    q, {"owner": USER, "name": repo["name"], "cursor": cursor}
                )
                st = (
                    ((data or {}).get("data") or {}).get("repository") or {}
                ).get("stargazers") or {}
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
                    f"{API}/repos/{USER}/{repo['name']}/stargazers"
                    f"?per_page=100&page={page}",
                    {
                        "User-Agent": UA,
                        "Accept": "application/vnd.github.star+json",
                    },
                    token=USER_TOKEN or TOKEN,
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


def collect(points, values, hist):
    today = datetime.date.today().isoformat()
    fresh = {}

    try:
        repos = fetch_repos()
    except Exception as e:
        print("repos failed:", e)
        return fresh

    star_dates = hist.get("star_dates") or []
    star_try_key = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H")
    if not star_dates and hist.get("meta", {}).get("star_try") != star_try_key:
        star_dates = fetch_star_dates_graphql(repos) or fetch_star_dates_rest(repos)
        hist.setdefault("meta", {})["star_try"] = star_try_key
        if star_dates:
            hist["star_dates"] = star_dates
    star_total = sum(r.get("stargazers_count", 0) for r in repos)
    repo_dates = [r["created_at"][:10] for r in repos if not r.get("private")]

    for d in points:
        iso = d.isoformat()
        if iso != today and iso in values:
            continue
        st = None
        if star_dates:
            st = sum(1 for x in star_dates if x < iso)
        elif iso == today:
            st = star_total
        else:
            st = values.get(iso, {}).get("stars")

        entry = {
            "stars": st,
            "repos": sum(1 for x in repo_dates if x < iso),
        }
        try:
            entry["prs"] = search_count(f"author:{USER} type:pr created:<{iso}", "issues")
            entry["issues"] = search_count(
                f"author:{USER} type:issue created:<{iso}", "issues"
            )
            entry["commits"] = search_count(
                f"author:{USER} author-date:<{iso}", "commits"
            )
        except Exception as e:
            print("search failed for", iso, e)
            if iso in values:
                entry.update({k: v for k, v in values[iso].items() if k not in entry})
        fresh[iso] = entry
        print(iso, entry)

    return fresh


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
        vals = [values.get(p, {}).get(key) for p in points]
        known = [v for v in vals if v is not None]
        cur = known[-1] if known else 0
        first = known[0] if known else 0
        delta = cur - first
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
            area = f"M {px(seen[0][0]):.1f},{y0 + sh} L " + " L ".join(
                f"{px(j):.1f},{py(v):.1f}" for j, v in seen
            ) + f" L {px(seen[-1][0]):.1f},{y0 + sh} Z"

        delta_label = (
            f"12 个月 +{fmt(delta)}"
            if values.get(points[0], {}).get(key) is not None
            else "自今日起记录"
        )

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
        font-family="PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif">近 12 个月 · 累计值 · 每小时同步</text>
  {''.join(rows)}
  {xlabels}
</svg>
'''


def write_debug():
    info = {"has_user_token": bool(USER_TOKEN), "has_gh_token": bool(TOKEN)}
    if USER_TOKEN:
        try:
            req = urllib.request.Request(
                f"{API}/user",
                headers={
                    "Authorization": f"Bearer {USER_TOKEN}",
                    "User-Agent": UA,
                },
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                info["login"] = json.load(r).get("login")
                info["scopes"] = r.headers.get("x-oauth-scopes")
        except Exception as e:
            info["user_error"] = str(e)
        try:
            info["search_pr_token"] = search_count(
                f"author:{USER} type:pr", "issues", pace=False
            )
        except Exception as e:
            info["search_pr_token_error"] = str(e)
        try:
            info["search_commits_token"] = search_count(
                f"author:{USER}", "commits", pace=False
            )
        except Exception as e:
            info["search_commits_token_error"] = str(e)
        try:
            rr = get(
                f"{API}/repos/{USER}/plus-extractor/stargazers?per_page=1",
                {"User-Agent": UA, "Accept": "application/vnd.github.star+json"},
                token=USER_TOKEN,
            )
            info["stargazers_rest_ok"] = isinstance(rr, list)
        except urllib.error.HTTPError as e:
            info["stargazers_rest_error"] = f"{e.code} {e.read()[:200].decode('utf-8', 'ignore')}"
        except Exception as e:
            info["stargazers_rest_error"] = str(e)
        try:
            q = """
            query($owner:String!, $name:String!) {
              repository(owner:$owner, name:$name) {
                stargazers(first:1) { totalCount }
              }
            }
            """
            data = graphql(q, {"owner": USER, "name": "plus-extractor"})
            info["graphql"] = data
        except urllib.error.HTTPError as e:
            info["graphql_error"] = f"{e.code} {e.read()[:300].decode('utf-8', 'ignore')}"
        except Exception as e:
            info["graphql_error"] = str(e)
    try:
        info["search_pr_anon"] = search_count(f"author:{USER} type:pr", "issues", pace=False)
    except Exception as e:
        info["search_pr_anon_error"] = str(e)
    try:
        info["search_commits_anon"] = search_count(f"author:{USER}", "commits", pace=False)
    except Exception as e:
        info["search_commits_anon_error"] = str(e)
    os.makedirs("data", exist_ok=True)
    with open("data/debug.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    print("debug:", info)
    return info


def main():
    points = [d.isoformat() for d in month_points(12)]

    history = {"points": {}, "meta": {}}
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass
    values = history.setdefault("points", {})
    info = write_debug()

    def _greater(key):
        a = info.get(f"search_{key}_token")
        b = info.get(f"search_{key}_anon")
        return isinstance(a, int) and isinstance(b, int) and a > b

    has_private = _greater("pr") or _greater("commits")
    if has_private and not history.get("meta", {}).get("private"):
        values.clear()
        history.setdefault("meta", {})["private"] = True

    fresh = collect(
        [datetime.date.fromisoformat(p) for p in points], values, history
    )
    if fresh:
        values.update(fresh)
        os.makedirs("data", exist_ok=True)
        with open(HISTORY, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=1, sort_keys=True)

    svg = render(points, values)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
