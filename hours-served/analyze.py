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
        "total2": "      at {i}m cutoff {t} (-{s:.0f}%)  ·  typed-only floor {f}",
        "weekly": "=== Weekly (weeks start Monday) ===",
        "weekly_row": "{a} ~ {b}  {t:>9}  ({d} days, {avg}/day)",
        "projects": "=== Top 3 projects per day ===",
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
        "total2": "     {i}분 기준 {t} (-{s:.0f}%)  ·  입력기준 하한 {f}",
        "weekly": "=== 주별 (월요일 시작) ===",
        "weekly_row": "{a} ~ {b}  {t:>9}  ({d}일, 일평균 {avg})",
        "projects": "=== 일자별 프로젝트 상위 3 ===",
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
    if arg_tz is not None:
        return dt.timezone(dt.timedelta(hours=arg_tz))
    return dt.datetime.now().astimezone().tzinfo


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
    if args.date_from:
        start = dt.datetime.fromisoformat(args.date_from).replace(tzinfo=tz) + off
    else:
        today = (dt.datetime.now(tz) - off).date()
        start = dt.datetime.combine(today - dt.timedelta(days=args.days - 1), dt.time(), tz) + off
    if args.date_to:
        end = dt.datetime.fromisoformat(args.date_to).replace(tzinfo=tz) + off + dt.timedelta(days=1)
    else:
        end = dt.datetime.now(tz) + dt.timedelta(seconds=1)
    return start, end


def is_real_user_prompt(rec):
    """True only for turns a human actually typed."""
    if rec.get("isSidechain") or rec.get("isMeta"):
        return False
    if rec.get("promptSource") == "sdk":  # harness-generated turns, e.g. branch naming
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        s = content.strip()
        stubs = ("<local-command-caveat>", "<command-name>", "<command-message>",
                 "<local-command-stdout>", "<system-reminder>", "<user-prompt-submit-hook>")
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
                # cheap reject first; full parse only for lines that can carry a timestamp
                if '"timestamp":"' not in line:
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


def hm(sec):
    return f"{int(sec // 3600)}h{int((sec % 3600) // 60):02d}m"


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
    rows = []
    for day in sorted(set(events) | set(prompts)):
        eps = events[day]
        rows.append(dict(
            day=day, wd=t["weekdays"][day.weekday()],
            active=active_seconds(eps, idle),
            active_tight=active_seconds(eps, tight),
            typed=active_seconds(prompts[day], idle),
            first=dt.datetime.fromtimestamp(min(eps), tz),
            last=dt.datetime.fromtimestamp(max(eps), tz),
            n_prompt=len(prompts[day]), n_session=len(sessions[day]), n_event=len(eps),
            top=sorted(projects[day].items(), key=lambda kv: -kv[1])[:3],
        ))

    tz_hours = tz.utcoffset(dt.datetime.now()).total_seconds() / 3600
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
                 hm(r["typed"]), r["first"].strftime("%H:%M"), r["last"].strftime("%H:%M"),
                 r["n_prompt"], r["n_session"]]
        print("".join(pad(c, w, x) for c, w, x in zip(cells, COL_W, right)))
    print("-" * width(line))

    total = sum(r["active"] for r in rows)
    total_tight = sum(r["active_tight"] for r in rows)
    shrink = (1 - total_tight / total) * 100 if total else 0
    print(t["total"].format(t=hm(total), d=len(rows), avg=hm(total / len(rows)),
                            p=sum(r["n_prompt"] for r in rows)))
    print(t["total2"].format(i=f"{args.idle_tight:g}", t=hm(total_tight), s=shrink,
                             f=hm(sum(r["typed"] for r in rows))))

    print("\n" + t["weekly"])
    weeks = defaultdict(list)
    for r in rows:
        weeks[r["day"] - dt.timedelta(days=r["day"].weekday())].append(r)
    for wk in sorted(weeks):
        rs = weeks[wk]
        s = sum(r["active"] for r in rs)
        print(t["weekly_row"].format(a=wk, b=wk + dt.timedelta(days=6), t=hm(s),
                                     d=len(rs), avg=hm(s / len(rs))))

    print("\n" + t["projects"])
    for r in rows:
        tops = ", ".join(f"{k.lstrip('-')}({v})" for k, v in r["top"])
        print(f"{r['day']} {r['wd']}  {tops}")

    if args.json_out:
        payload = [{**r, "day": r["day"].isoformat(), "first": r["first"].isoformat(),
                    "last": r["last"].isoformat()} for r in rows]
        with open(args.json_out, "w") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(t["saved"].format(path=args.json_out), file=sys.stderr)


if __name__ == "__main__":
    main()
