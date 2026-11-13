#!/usr/bin/env python3
import datetime
import json
import os
import pathlib
import re
import urllib.request

LOGIN = os.environ.get("DASHBOARD_LOGIN", "marinoszago")
ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

THEMES = {
    "light": {
        "panel": "#ffffff",
        "border": "#d0d7de",
        "grid": "#e6e9ec",
        "text": "#1f2328",
        "muted": "#59636e",
        "bar": "#2a78d6",
        "heat": ["#eff2f5", "#86b6ef", "#3987e5", "#256abf", "#104281"],
    },
    "dark": {
        "panel": "#0d1117",
        "border": "#3d444d",
        "grid": "#21262d",
        "text": "#f0f6fc",
        "muted": "#9198a1",
        "bar": "#3987e5",
        "heat": ["#151b23", "#184f95", "#2a78d6", "#5598e7", "#9ec5f4"],
    },
}

WIDTH = 840
PAD = 24
GAP = 12


def graphql(query, variables=None):
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {os.environ['GH_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    if "errors" in payload:
        raise SystemExit(f"GitHub GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


CALENDAR = "restrictedContributionsCount contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }"


def fetch():
    user = graphql(
        f"query($login: String!) {{ user(login: $login) {{ contributionsCollection {{ contributionYears {CALENDAR} }} }} }}",
        {"login": LOGIN},
    )
    recent = user["contributionsCollection"]
    years = {}
    for year in recent["contributionYears"]:
        collection = graphql(
            f"query($login: String!, $from: DateTime!, $to: DateTime!) {{ user(login: $login) {{ contributionsCollection(from: $from, to: $to) {{ {CALENDAR} }} }} }}",
            {"login": LOGIN, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["contributionsCollection"]
        years[year] = collection
    return recent, years


def days_of(collection):
    return [day for week in collection["contributionCalendar"]["weeks"] for day in week["contributionDays"]]


def streaks(all_days, today):
    counts = {datetime.date.fromisoformat(day["date"]): day["contributionCount"] for day in all_days}
    longest = run = 0
    for date in sorted(counts):
        run = run + 1 if counts[date] else 0
        longest = max(longest, run)
    cursor = today if counts.get(today) else today - datetime.timedelta(days=1)
    current = 0
    while counts.get(cursor):
        current += 1
        cursor -= datetime.timedelta(days=1)
    return longest, current


def quartile_levels(days):
    nonzero = sorted(day["contributionCount"] for day in days if day["contributionCount"])
    if not nonzero:
        return [1, 1, 1]
    return [nonzero[int(len(nonzero) * share)] for share in (0.25, 0.5, 0.75)]


def level(count, thresholds):
    if count == 0:
        return 0
    return 1 + sum(count > threshold for threshold in thresholds)


def text(x, y, content, size, fill, weight=400, anchor="start"):
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{content}</text>'


def panel(y, height, theme):
    return f'<rect x="0.5" y="{y + 0.5}" width="{WIDTH - 1}" height="{height - 1}" rx="8" fill="{theme["panel"]}" stroke="{theme["border"]}"/>'


def rounded_bar(x, y, width, height, radius=4):
    radius = min(radius, height, width / 2)
    return (
        f"M{x},{y + height} V{y + radius} Q{x},{y} {x + radius},{y} "
        f"H{x + width - radius} Q{x + width},{y} {x + width},{y + radius} V{y + height} Z"
    )


def render(theme, data):
    parts = []
    tile_width = (WIDTH - 3 * GAP) / 4
    for index, (value, label, note) in enumerate(data["tiles"]):
        x = index * (tile_width + GAP)
        parts.append(f'<rect x="{x + 0.5}" y="0.5" width="{tile_width - 1}" height="95" rx="8" fill="{theme["panel"]}" stroke="{theme["border"]}"/>')
        parts.append(text(x + 16, 26, label, 12, theme["muted"]))
        parts.append(text(x + 16, 60, value, 28, theme["text"], 600))
        parts.append(text(x + 16, 80, note, 11, theme["muted"]))

    heat_top = 96 + GAP
    cell, pitch = 11, 14
    weeks = data["weeks"]
    grid_left = PAD + 30
    parts.append(panel(heat_top, 200, theme))
    parts.append(text(PAD, heat_top + 30, "Contributions, last 12 months", 14, theme["text"], 600))
    grid_top = heat_top + 64
    previous_month = None
    for column, week in enumerate(weeks):
        month = week[0]["date"][5:7]
        if month != previous_month and column < len(weeks) - 2:
            name = datetime.date.fromisoformat(week[0]["date"]).strftime("%b")
            parts.append(text(grid_left + column * pitch, grid_top - 8, name, 10, theme["muted"]))
        previous_month = month
        for day in week:
            row = datetime.date.fromisoformat(day["date"]).isoweekday() % 7
            fill = theme["heat"][level(day["contributionCount"], data["thresholds"])]
            parts.append(
                f'<rect x="{grid_left + column * pitch}" y="{grid_top + row * pitch}" width="{cell}" height="{cell}" rx="2" fill="{fill}">'
                f'<title>{day["date"]}: {day["contributionCount"]}</title></rect>'
            )
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(text(PAD, grid_top + row * pitch + 9, name, 10, theme["muted"]))
    legend_y = grid_top + 7 * pitch + 10
    legend_right = grid_left + len(weeks) * pitch - 3
    swatches_left = legend_right - 5 * pitch + 3
    parts.append(text(swatches_left - 6, legend_y + 9, "Less", 10, theme["muted"], anchor="end"))
    for index, fill in enumerate(theme["heat"]):
        parts.append(f'<rect x="{swatches_left + index * pitch}" y="{legend_y}" width="{cell}" height="{cell}" rx="2" fill="{fill}"/>')
    parts.append(text(legend_right + 6, legend_y + 9, "More", 10, theme["muted"]))

    bars_top = heat_top + 200 + GAP
    plot_height = 140
    parts.append(panel(bars_top, 250, theme))
    parts.append(text(PAD, bars_top + 30, "Contributions per year", 14, theme["text"], 600))
    baseline = bars_top + 60 + plot_height
    yearly = data["yearly"]
    peak = max(total for _, total in yearly) or 1
    labelled = {year for year, _ in sorted(yearly, key=lambda item: item[1], reverse=True)[:3]}
    slot = (WIDTH - 2 * PAD) / len(yearly)
    bar_width = min(28, slot - 8)
    parts.append(f'<line x1="{PAD}" x2="{WIDTH - PAD}" y1="{baseline + 0.5}" y2="{baseline + 0.5}" stroke="{theme["grid"]}"/>')
    for index, (year, total) in enumerate(yearly):
        center = PAD + slot * index + slot / 2
        height = max(total / peak * plot_height, 2 if total else 0)
        if height:
            parts.append(
                f'<path d="{rounded_bar(center - bar_width / 2, baseline - height, bar_width, height)}" fill="{theme["bar"]}">'
                f"<title>{year}: {total:,}</title></path>"
            )
        if year in labelled:
            parts.append(text(center, baseline - height - 6, f"{total:,}", 11, theme["text"], 600, "middle"))
        parts.append(text(center, baseline + 18, str(year), 11, theme["muted"], anchor="middle"))

    footer_y = bars_top + 250 + 22
    parts.append(text(0, footer_y, f"Private contributions show as counts only. Updated {data['updated']}.", 11, theme["muted"]))

    height = footer_y + 6
    label = (
        f"GitHub activity for {LOGIN}: {data['tiles'][0][0]} contributions in the last 12 months, "
        f"{data['tiles'][1][0]} since {yearly[0][0]}."
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" '
        f'role="img" aria-label="{label}" font-family="{FONT}"><title>{label}</title>'
        + "".join(parts)
        + "</svg>\n"
    )


def update_readme_table(yearly):
    readme = ROOT / "README.md"
    rows = "\n".join(f"| {year} | {total:,} | {private:,} |" for year, total, private in reversed(yearly))
    table = f"| Year | Contributions | Private |\n| --- | ---: | ---: |\n{rows}"
    content = readme.read_text()
    content = re.sub(
        r"(<!-- yearly:start -->).*?(<!-- yearly:end -->)",
        lambda match: f"{match.group(1)}\n{table}\n{match.group(2)}",
        content,
        flags=re.S,
    )
    readme.write_text(content)


def main():
    today = datetime.datetime.now(datetime.timezone.utc).date()
    recent, years = fetch()
    all_days = [day for collection in years.values() for day in days_of(collection)]
    longest, current = streaks(all_days, today)
    last_year_total = recent["contributionCalendar"]["totalContributions"]
    yearly = sorted(
        (year, collection["contributionCalendar"]["totalContributions"], collection["restrictedContributionsCount"])
        for year, collection in years.items()
    )
    all_time = sum(total for _, total, _ in yearly)
    data = {
        "tiles": [
            (f"{last_year_total:,}", "Last 12 months", f"{recent['restrictedContributionsCount']:,} in private repos"),
            (f"{all_time:,}", "All time", f"since {yearly[0][0]}"),
            (f"{longest}", "Longest streak", "days in a row"),
            (f"{current}", "Current streak", "days in a row"),
        ],
        "weeks": [week["contributionDays"] for week in recent["contributionCalendar"]["weeks"]],
        "thresholds": quartile_levels(days_of(recent)),
        "yearly": [(year, total) for year, total, _ in yearly],
        "updated": today.isoformat(),
    }
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (assets / f"dashboard-{name}.svg").write_text(render(theme, data))
    update_readme_table(yearly)


if __name__ == "__main__":
    main()
