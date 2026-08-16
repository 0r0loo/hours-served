#!/usr/bin/env python3
"""Reconstruct daily working hours from Claude Code session logs.

Reads every ~/.claude/projects/**/*.jsonl transcript, merges all sessions into a
single timeline, and stitches together the gaps that are short enough to count as
work. Concurrent sessions (multiple worktrees, subagents) are never summed twice.

Usage:
  python3 analyze.py                          # last 3 weeks
  python3 analyze.py --days 7                 # last week
  python3 analyze.py --from 2026-07-25 --to 2026-08-15
  python3 analyze.py --day-start 0            # midnight day boundary (default 5am)
  python3 analyze.py --idle 15                # 15-minute idle cutoff (default 30)
  python3 analyze.py --only myrepo            # only projects matching a substring
  python3 analyze.py --lang ko                # Korean output
  python3 analyze.py --json out.json          # dump raw per-day numbers

No dependencies. Python 3.8+, standard library only. Reads local files only and
never sends anything anywhere.
"""
import argparse
import datetime as dt
import json
import os
import sys
import unicodedata
from collections import defaultdict

STR = {
    "en": {
        "scanning": "scanning {n} session files...",
        "no_root": "Session log directory not found: {root}",
        "no_data": "No session records in that period.",
        "period": "Period {a} ~ {b}  ·  day starts {h}:00  ·  idle cutoff {i}m  ·  UTC{tz}",
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "col": ["Date", "Day", "Active", "({i}m)", "Typed", "First", "Last", "Prompts", "Sess"],
        "total": "TOTAL {t} over {d} days  ·  {avg}/day  ·  {p:,} prompts",
        "total2": "      {w} days worked, {o} off  ·  longest streak {s} days  ·  {avgw}/day worked",
        "total3": "      at {i}m cutoff {t} (-{s:.0f}%)  ·  typed-only floor {f}",
        "weekly": "=== Weekly (weeks start Monday) ===",
        "weekly_row": "{a} ~ {b}  {t:>9}  ({w} of {d} days worked, {avg}/day)",
        "clock": "=== When the work happens (share of active time) ===",
        "buckets": [("late night 00-05", 0, 5), ("morning 05-09", 5, 9),
                    ("daytime 09-18", 9, 18), ("evening 18-24", 18, 24)],
        "projects": "=== Top 3 projects per day ===",
        "day_off": "(off)",
        "saved": "JSON written: {path}",
    },
    "ko": {
        "scanning": "세션 파일 {n}개 스캔 중...",
        "no_root": "세션 로그 폴더가 없습니다: {root}",
        "no_data": "해당 기간에 세션 기록이 없습니다.",
        "period": "기간 {a} ~ {b}  ·  하루 경계 {h}시  ·  유휴 {i}분  ·  UTC{tz}",
        "weekdays": ["월", "화", "수", "목", "금", "토", "일"],
        "col": ["날짜", "요일", "활동", "({i}m)", "입력기준", "첫활동", "끝", "프롬프트", "세션"],
        "total": "합계 {t} / {d}일  ·  일평균 {avg}  ·  프롬프트 {p:,}건",
        "total2": "     일한 날 {w}일, 쉰 날 {o}일  ·  최장 연속 {s}일  ·  일한 날 평균 {avgw}",
        "total3": "     {i}분 기준 {t} (-{s:.0f}%)  ·  입력기준 하한 {f}",
        "weekly": "=== 주별 (월요일 시작) ===",
        "weekly_row": "{a} ~ {b}  {t:>9}  ({d}일 중 {w}일 일함, 일평균 {avg})",
        "clock": "=== 몇 시에 일하는가 (활동시간 비중) ===",
        "buckets": [("심야 00-05시", 0, 5), ("아침 05-09시", 5, 9),
                    ("낮 09-18시", 9, 18), ("저녁 18-24시", 18, 24)],
        "projects": "=== 일자별 프로젝트 상위 3 ===",
        "day_off": "(휴무)",
        "saved": "JSON 저장: {path}",
    },
}

COL_W = [11, 5, 9, 9, 10, 8, 7, 9, 6]


def build_parser():
    p = argparse.ArgumentParser(
        description="Reconstruct daily working hours from Claude Code session logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--days", type=int, default=21,
                   help="look back N days (default 21). Ignored when --from is given")
    p.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="start date (inclusive)")
    p.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="end date (inclusive)")
    p.add_argument("--day-start", type=float, default=5.0, metavar="H",
                   help="hour that starts a new day (default 5) -> 3am work counts as the day before")
    p.add_argument("--idle", type=float, default=30.0, metavar="MIN",
                   help="only stitch gaps up to this many minutes (default 30)")
    p.add_argument("--idle-tight", type=float, default=15.0, metavar="MIN",
                   help="second, stricter cutoff shown alongside for sensitivity (default 15)")
    p.add_argument("--tz", type=float, default=None, metavar="H",
                   help="UTC offset in hours (default: your local timezone)")
    p.add_argument("--root", default=None, help="session log root (default ~/.claude/projects)")
    p.add_argument("--only", action="append", default=[], metavar="SUBSTR",
                   help="count only projects whose path contains SUBSTR (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="SUBSTR",
                   help="skip projects whose path contains SUBSTR (repeatable)")
    p.add_argument("--lang", choices=sorted(STR), default=None,
                   help="output language (default: from your locale, else en)")
    p.add_argument("--json", dest="json_out", metavar="PATH", help="write per-day numbers as JSON")
    return p


def pick_lang(arg_lang):
    if arg_lang:
        return arg_lang
    env = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
           or os.environ.get("LANG") or "")
    return "ko" if env.lower().startswith("ko") else "en"


def local_tz(arg_tz):
    """A fixed offset for --tz, else None meaning 'the system zone'.

    None is deliberate. Freezing today's offset onto every date in the window
    shifts historical timestamps by an hour whenever the window crosses a DST
    change, and the day boundary shifts with them, so events near it land on the
    wrong date. Passing None to astimezone() resolves the offset per timestamp.
    """
    if arg_tz is not None:
        return dt.timezone(dt.timedelta(hours=arg_tz))
    return None


def as_local(naive, tz):
    """Read a naive wall-clock time in the target zone, honouring DST on that date."""
    if tz is not None:
        return naive.replace(tzinfo=tz)
    return naive.astimezone()  # a naive datetime is presumed to be system-local


def from_epoch(ep, tz):
    """Epoch seconds -> an aware datetime in the target zone."""
    return dt.datetime.fromtimestamp(ep, dt.timezone.utc).astimezone(tz)


def now_in(tz):
    return dt.datetime.now(dt.timezone.utc).astimezone(tz)


def resolve_root(arg_root):
    if arg_root:
        return os.path.expanduser(arg_root)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg:
        return os.path.join(os.path.expanduser(cfg), "projects")
    return os.path.expanduser("~/.claude/projects")


def resolve_window(args, tz):
    """Return [start, end). `end` is the day after --to, at the day-start hour."""
    off = dt.timedelta(hours=args.day_start)
    # shift the naive wall clock first, then localise, so the offset is the one in
    # force on that date rather than the one in force today
    if args.date_from:
        start = as_local(dt.datetime.fromisoformat(args.date_from) + off, tz)
    else:
        today = (now_in(tz) - off).date()
        first = today - dt.timedelta(days=args.days - 1)
        start = as_local(dt.datetime.combine(first, dt.time()) + off, tz)
    if args.date_to:
        end = as_local(dt.datetime.fromisoformat(args.date_to) + off + dt.timedelta(days=1), tz)
    else:
        end = now_in(tz) + dt.timedelta(seconds=1)
    return start, end


def is_real_user_prompt(rec):
    """True only for turns a human actually typed."""
    if rec.get("isSidechain") or rec.get("isMeta"):
        return False
    # harness-generated turns: "sdk" = branch naming and the like, "system" = background
    # task notifications. "typed" and "queued" are both the human at the keyboard.
    if rec.get("promptSource") in ("sdk", "system"):
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        s = content.strip()
        # belt and braces: older transcripts predate promptSource entirely
        stubs = ("<local-command-caveat>", "<command-name>", "<command-message>",
                 "<local-command-stdout>", "<system-reminder>", "<user-prompt-submit-hook>",
                 "<task-notification>")
        return bool(s) and not s.startswith(stubs)
    if isinstance(content, list):
        # a user record carrying only tool_result blocks is not a human turn
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
    return False


def collect(root, start, end, tz, day_start, only, exclude, t):
    events = defaultdict(list)      # day -> [epoch]  every activity
    prompts = defaultdict(list)     # day -> [epoch]  human-typed turns only
    sessions = defaultdict(set)     # day -> {session file}
    projects = defaultdict(lambda: defaultdict(int))  # day -> project -> event count

    files = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if not n.endswith(".jsonl"):
                continue
            path = os.path.join(dirpath, n)
            if only and not any(s in path for s in only):
                continue
            if exclude and any(s in path for s in exclude):
                continue
            try:  # never open a file last written before the window
                if os.path.getmtime(path) < start.timestamp() - 86400:
                    continue
            except OSError:
                continue
            files.append((path, os.path.basename(dirpath)))

    print(t["scanning"].format(n=len(files)), file=sys.stderr)
    offset = dt.timedelta(hours=day_start)

    for path, project in files:
        try:
            fh = open(path, "r", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                # cheap reject first; full parse only for lines that can carry a
                # timestamp. Kept whitespace-insensitive on purpose: matching the
                # compact '"timestamp":"' would silently drop every line if the
                # transcripts were ever written with spaces after the colon.
                if "timestamp" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                raw = rec.get("timestamp")
                if not raw:
                    continue
                try:
                    ts = dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(tz)
                except (ValueError, AttributeError):
                    continue
                if not (start <= ts < end):
                    continue
                day = (ts - offset).date()
                events[day].append(ts.timestamp())
                sessions[day].add(path)
                projects[day][project] += 1
                if rec.get("type") == "user" and is_real_user_prompt(rec):
                    prompts[day].append(ts.timestamp())

    return events, prompts, sessions, projects


def active_seconds(eps, idle_gap):
    """Total seconds, stitching only the gaps that are at most idle_gap long."""
    if not eps:
        return 0.0
    eps = sorted(eps)
    return sum(b - a for a, b in zip(eps, eps[1:]) if b - a <= idle_gap)


def hour_histogram(eps, idle_gap, tz, hours=None):
    """Same stitched spans as active_seconds, but split across the clock hours they
    cover. A span from 23:40 to 00:20 is 20 minutes of hour 23 and 20 of hour 0 —
    not 40 minutes of whichever end you happened to pick."""
    hours = [0.0] * 24 if hours is None else hours
    eps = sorted(eps)
    for a, b in zip(eps, eps[1:]):
        if b - a > idle_gap:
            continue
        cur = a
        while cur < b:
            here = from_epoch(cur, tz)
            edge = (here.replace(minute=0, second=0, microsecond=0)
                    + dt.timedelta(hours=1)).timestamp()
            stop = min(b, edge)
            hours[here.hour] += stop - cur
            cur = stop
    return hours


SPARK = " ▁▂▃▄▅▆▇█"


def sparkline(values):
    peak = max(values) or 1
    return "".join(SPARK[min(len(SPARK) - 1, int(v / peak * (len(SPARK) - 1) + 0.5))]
                   for v in values)


def longest_streak(rows):
    """Most consecutive days worked without one off."""
    best = run = 0
    for r in rows:
        run = run + 1 if r["n_event"] else 0
        best = max(best, run)
    return best


def hm(sec):
    if sec < 60:  # a day off, or a day with a single stray event
        return "0m"
    return f"{int(sec // 3600)}h{int((sec % 3600) // 60):02d}m"


def span_days(first, last):
    """Every calendar day from first to last inclusive, so days off keep their row."""
    out, day = [], first
    while day <= last:
        out.append(day)
        day += dt.timedelta(days=1)
    return out


def width(s):
    """Terminal columns a string occupies (CJK glyphs take two)."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, w, right=False):
    s = str(s)
    fill = " " * max(0, w - width(s))
    return fill + s if right else s + fill


def main():
    args = build_parser().parse_args()
    t = STR[pick_lang(args.lang)]
    tz = local_tz(args.tz)
    root = resolve_root(args.root)
    if not os.path.isdir(root):
        sys.exit(t["no_root"].format(root=root))

    start, end = resolve_window(args, tz)
    events, prompts, sessions, projects = collect(
        root, start, end, tz, args.day_start, args.only, args.exclude, t
    )
    if not events:
        sys.exit(t["no_data"])

    idle, tight = args.idle * 60, args.idle_tight * 60
    worked = sorted(set(events) | set(prompts))
    rows = []
    # every day between the first and last day of activity, so a day off is a visible
    # row rather than a hole in the date column. No leading/trailing zero padding.
    for day in span_days(worked[0], worked[-1]):
        eps = events.get(day) or []
        rows.append(dict(
            day=day, wd=t["weekdays"][day.weekday()],
            active=active_seconds(eps, idle),
            active_tight=active_seconds(eps, tight),
            typed=active_seconds(prompts.get(day) or [], idle),
            first=from_epoch(min(eps), tz) if eps else None,
            last=from_epoch(max(eps), tz) if eps else None,
            n_prompt=len(prompts.get(day) or []), n_session=len(sessions.get(day) or ()),
            n_event=len(eps),
            top=sorted(projects[day].items(), key=lambda kv: -kv[1])[:3] if eps else [],
        ))

    tz_hours = now_in(tz).utcoffset().total_seconds() / 3600
    # label the period with the day keys actually counted, not the shifted boundary
    print("\n" + t["period"].format(a=rows[0]["day"], b=rows[-1]["day"], h=f"{args.day_start:g}",
                                    i=f"{args.idle:g}", tz=f"{tz_hours:+g}") + "\n")

    cols = [c.format(i=f"{args.idle_tight:g}") for c in t["col"]]
    right = [False, False, True, True, True, True, True, True, True]
    line = "".join(pad(c, w, r) for c, w, r in zip(cols, COL_W, right))
    print(line)
    print("-" * width(line))
    for r in rows:
        cells = [r["day"].isoformat(), r["wd"], hm(r["active"]), hm(r["active_tight"]),
                 hm(r["typed"]),
                 r["first"].strftime("%H:%M") if r["first"] else "-",
                 r["last"].strftime("%H:%M") if r["last"] else "-",
                 r["n_prompt"], r["n_session"]]
        print("".join(pad(c, w, x) for c, w, x in zip(cells, COL_W, right)))
    print("-" * width(line))

    total = sum(r["active"] for r in rows)
    total_tight = sum(r["active_tight"] for r in rows)
    shrink = (1 - total_tight / total) * 100 if total else 0
    n_worked = sum(1 for r in rows if r["n_event"])
    print(t["total"].format(t=hm(total), d=len(rows), avg=hm(total / len(rows)),
                            p=sum(r["n_prompt"] for r in rows)))
    print(t["total2"].format(w=n_worked, o=len(rows) - n_worked, s=longest_streak(rows),
                             avgw=hm(total / n_worked) if n_worked else hm(0)))
    print(t["total3"].format(i=f"{args.idle_tight:g}", t=hm(total_tight), s=shrink,
                             f=hm(sum(r["typed"] for r in rows))))

    print("\n" + t["weekly"])
    weeks = defaultdict(list)
    for r in rows:
        weeks[r["day"] - dt.timedelta(days=r["day"].weekday())].append(r)
    for wk in sorted(weeks):
        rs = weeks[wk]
        s = sum(r["active"] for r in rs)
        print(t["weekly_row"].format(a=wk, b=wk + dt.timedelta(days=6), t=hm(s),
                                     d=len(rs), w=sum(1 for r in rs if r["n_event"]),
                                     avg=hm(s / len(rs))))

    clock = [0.0] * 24
    for day in events:
        hour_histogram(events[day], idle, tz, clock)
    span = sum(clock) or 1
    print("\n" + t["clock"])
    print("0h " + sparkline(clock) + " 24h")
    print("  ·  ".join(f"{name} {100 * sum(clock[a:b]) / span:.0f}%"
                       for name, a, b in t["buckets"]))

    print("\n" + t["projects"])
    for r in rows:
        tops = ", ".join(f"{k.lstrip('-')}({v})" for k, v in r["top"]) or t["day_off"]
        print(f"{r['day']} {r['wd']}  {tops}")

    if args.json_out:
        payload = [{**r, "day": r["day"].isoformat(),
                    "first": r["first"].isoformat() if r["first"] else None,
                    "last": r["last"].isoformat() if r["last"] else None} for r in rows]
        with open(args.json_out, "w") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(t["saved"].format(path=args.json_out), file=sys.stderr)


if __name__ == "__main__":
    main()
