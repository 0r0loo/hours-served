# hours-served

**How many hours did you *actually* work?**

Claude Code already writes down everything you do, with timestamps, to
`~/.claude/projects/`. `hours-served` reads those session logs and rebuilds a
daily working-hours timeline from them.

No tracker to install. No configuration. No account. It reads local files and
sends nothing anywhere — the whole thing is one dependency-free Python script.

```
$ python3 analyze.py --days 7

Period 2026-03-09 ~ 2026-03-15  ·  day starts 5:00  ·  idle cutoff 30m  ·  UTC+9

Date       Day     Active    (15m)     Typed   First   Last  Prompts  Sess
--------------------------------------------------------------------------
2026-03-09 Mon      9h12m    8h05m     7h44m   10:22  22:41      131    12
2026-03-10 Tue     11h48m   10h31m     9h27m   09:58  02:36      168    19
2026-03-11 Wed      4h35m    4h02m     3h58m   13:10  19:45       61     6
2026-03-12 Thu     10h04m    8h49m     8h11m   10:41  01:12      144    15
2026-03-13 Fri      7h21m    6h38m     6h05m   11:03  20:17       96     9
2026-03-14 Sat      3h52m    2h44m     2h19m   15:30  23:08       38     4
2026-03-15 Sun         0m       0m        0m       -      -        0     0
--------------------------------------------------------------------------
TOTAL 46h52m over 7 days  ·  6h41m/day  ·  638 prompts
      6 days worked, 1 off  ·  7h48m/day worked
      at 15m cutoff 40h49m (-13%)  ·  typed-only floor 37h44m
```

*(numbers above are illustrative)*

## Install

### As a Claude Code skill

```bash
git clone https://github.com/0r0loo/hours-served.git
cp -r hours-served/hours-served ~/.claude/skills/
```

Then just ask, in whatever language you speak:

```
/hours-served
"how many hours did I work this week?"
```

Claude runs the script, reads the rules in `SKILL.md`, and writes the report —
including the caveats, which matter more than the number.

### As a plain script

You do not need Claude Code to run it. Grab the one file:

```bash
curl -O https://raw.githubusercontent.com/0r0loo/hours-served/main/hours-served/analyze.py
python3 analyze.py
```

Python 3.8+, standard library only.

## Usage

```
--days 21                     look back N days (default 21)
--from 2026-07-25 --to 2026-08-15
--only myrepo                 count only projects matching a substring (repeatable)
--exclude sideproject         skip projects matching a substring (repeatable)
--day-start 0                 midnight day boundary (default 5am)
--idle 15                     idle cutoff in minutes (default 30)
--tz 0                        UTC offset (default: your local timezone)
--lang ko                     output language (default: from your locale)
--json out.json               dump per-day numbers
--root PATH                   session log root (default ~/.claude/projects)
```

## How it counts

Five decisions produce the number. They are worth knowing before you quote it.

**Every session is merged into one timeline.** You might have five worktrees and a
dozen subagents running at once, but you only have one body. Summing per session
would hand you 30-hour days.

**Only gaps of 30 minutes or less are stitched.** Lunch, meetings and going home
are not work. A longer gap is dropped entirely rather than partially counted.

**A day starts at 05:00.** Work at 3am belongs to the previous day. With a midnight
boundary, one all-nighter is split across two dates and both of them lie.

**Two numbers, not one.** *Active* stitches all short gaps, so it leans high.
*Typed* spans only turns you typed yourself, so it leans low. The truth is between
them, and the tool refuses to pretend otherwise.

**A day off keeps its row.** Every calendar day between your first and last day of
activity is printed, even at `0m`. A missing date is easy to read straight past; a
row of zeros is not. The totals give you both averages — over the calendar, and over
the days you actually worked.

## What it cannot tell you

- **Active is closer to a ceiling.** Walking away while Claude works still counts,
  as long as the next event lands within the cutoff. `--idle 15` typically trims ~10%.
- **Typed is a floor.** It measures only the spans between your own keystrokes.
- **Work without Claude is invisible.** Meetings, Slack, browser QA, reading code,
  querying a production database — none of it is here. Your real hours are certainly
  higher than the table shows.

This is not an attendance record and should not be used as one. It is a mirror, and
mainly a useful one when the reflection is worse than you expected.

## Privacy

Everything is read from local disk and nothing is transmitted. One thing to watch:
the **"Top 3 projects per day"** section prints directory names — your repo and
worktree names. Check that section before sharing a screenshot.

---

<a name="korean"></a>

# 한국어

**나는 실제로 몇 시간 일했나?**

Claude Code 는 이미 당신이 한 모든 일을 타임스탬프와 함께
`~/.claude/projects/` 에 기록하고 있습니다. `hours-served` 는 그 세션 로그를 읽어
일자별 노동시간 타임라인을 복원합니다.

트래커 설치도, 설정도, 계정도 필요 없습니다. 로컬 파일만 읽고 어디로도 전송하지
않습니다. 의존성 없는 파이썬 스크립트 한 개가 전부입니다.

## 설치

**Claude Code 스킬로 쓰기**

```bash
git clone https://github.com/0r0loo/hours-served.git
cp -r hours-served/hours-served ~/.claude/skills/
```

이후 `/hours-served` 로 부르거나 그냥 "나 이번 주에 몇 시간 일했지?" 라고 물으면
됩니다. 한국어로 물으면 한국어로 나옵니다.

**스크립트만 쓰기**

```bash
curl -O https://raw.githubusercontent.com/0r0loo/hours-served/main/hours-served/analyze.py
python3 analyze.py --lang ko
```

## 어떻게 세는가

**모든 세션을 하나의 타임라인으로 합칩니다.** 워크트리 다섯 개를 동시에 굴려도
몸은 하나입니다. 세션별로 더하면 하루가 30시간이 됩니다.

**공백이 30분 이하일 때만 이어붙입니다.** 점심·회의·퇴근은 근무가 아닙니다.
30분을 넘긴 공백은 통째로 버립니다.

**하루 경계는 05:00 입니다.** 새벽 3시 작업은 전날에 붙습니다. 자정 기준이면
밤샘 하루가 반토막 나 양쪽 날짜가 다 거짓이 됩니다.

**숫자는 한 쌍입니다.** *활동시간* 은 짧은 공백을 모두 이어붙이므로 상한에
가깝고, *입력기준* 은 직접 친 프롬프트 사이만 재므로 하한입니다. 진짜 값은 그
사이에 있고, 이 도구는 그걸 하나의 숫자인 척하지 않습니다.

**쉰 날도 행으로 남깁니다.** 첫 활동일과 마지막 활동일 사이의 모든 날짜가 `0m`
으로라도 찍힙니다. 날짜가 비어 있으면 그냥 넘겨 읽기 쉽지만 0 으로 채워진 행은
그렇지 않습니다. 합계에는 달력 기준 평균과 일한 날 기준 평균이 함께 나옵니다.

## 이 숫자가 말하지 못하는 것

- **활동시간은 상한에 가깝습니다.** Claude 가 도는 동안 자리를 비웠어도 30분 안에
  다음 이벤트가 있으면 포함됩니다. `--idle 15` 로 조이면 보통 10% 안팎 줄어듭니다.
- **입력기준은 하한입니다.** 직접 친 프롬프트 사이만 잰 값입니다.
- **Claude 를 안 쓴 일은 아예 안 잡힙니다.** 회의, 슬랙, 브라우저 QA, 코드 읽기,
  운영 DB 조회 — 전부 빠집니다. 실제 근무시간은 이 표보다 확실히 많습니다.

근태 기록으로는 쓸 수 없습니다. 이건 거울이고, 비친 모습이 예상보다 나쁠 때
비로소 쓸모가 있습니다.

## 개인정보

전부 로컬에서만 읽고 아무것도 전송하지 않습니다. 다만 출력의 **"Top 3 projects
per day"** 줄에 저장소·워크트리 폴더명이 그대로 드러납니다. 스크린샷을 공유하기
전에 그 줄을 확인하세요.

## License

MIT
