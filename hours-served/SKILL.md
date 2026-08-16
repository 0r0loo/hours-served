---
name: hours-served
description: Reconstruct how many hours you actually worked, from Claude Code's own session logs. Use for "how many hours did I work", "my hours this week", "how hard have I been grinding", weekly timesheets, and burnout self-checks.
keywords: [hours, work hours, working hours, timesheet, time tracking, overtime, burnout, grind, how long did I work, 업무시간, 근무시간, 작업시간, 노동시간, 몇시간, 야근, 주간보고]
argument-hint: "[period — e.g. 3 weeks | last 7 days | 2026-07-25~2026-08-15 | blank = last 3 weeks]"
user-invocable: true
---

# hours-served

> Rebuild a daily working-hours timeline from `~/.claude/projects/**/*.jsonl`.
> This measures **when the keyboard was alive**, not when you clocked in.

<context>

## Where the data comes from

Claude Code writes every session to `~/.claude/projects/<project>/<session-id>.jsonl`.
One line is one event — a user turn, a model response, a tool call, a tool result — and
every line carries a `timestamp`. That pile of timestamps is a footprint of the work.
Nothing to install, nothing to configure, and it is already sitting on the disk.

`${CLAUDE_SKILL_DIR}/analyze.py` does the measuring. Standard library only, read-only,
fully offline.

</context>

<instructions>

## How to run it

1. **Turn the requested period into flags.**

   | User says | Command |
   |---|---|
   | (nothing) | `python3 "${CLAUDE_SKILL_DIR}/analyze.py"` |
   | "last 3 weeks", "lately" | `--days 21` |
   | "this week" | `--days 7` |
   | "Jul 25 to Aug 15" | `--from 2026-07-25 --to 2026-08-15` |
   | "only work, not side projects" | `--only <repo-substring>` (repeatable) |
   | "count my 3am sessions on that same day" | `--day-start 0` |

2. **Match the output language to the conversation.** Add `--lang ko` when the user is
   writing in Korean; otherwise the default is fine.

3. **Report using the `<output>` shape below**, and always attach `<limits>`.

</instructions>

<rules>

## Counting rules

These rules are what turn timestamps into a number. Change them freely — but when you
change one, say so in the report.

| # | Rule | Why |
|---|------|-----|
| 1 | **Merge every session into one timeline** | You can run five worktrees at once, but you only have one body. Summing per session produces 30-hour days. |
| 2 | **Only stitch gaps of 30 minutes or less** | Lunch, meetings and going home are not work. A longer gap is dropped whole, not halved. |
| 3 | **A day starts at 05:00** | 3am work belongs to the **previous** day. On a midnight boundary an all-nighter is split in two and both dates end up lying. |
| 4 | **"Typed" is a floor, not the answer** | It only spans turns the human actually typed. The truth sits between Active and Typed. |
| 5 | **Drop harness-generated turns from the prompt count** | Auto-generated branch names (`promptSource: sdk`), background task notifications (`promptSource: system`), command stubs and subagent turns were not typed by a person. `typed` and `queued` are. They all still count as *activity*, since a human action triggered them. |
| 6 | **Give a range, not a single number** | Say "7 to 8 hours", not "7h39m". The shape of the number should admit it is an estimate. |
| 7 | **A day off gets a row, not a gap** | A missing date is easy to read straight past. `0m ... - -` is not. The script emits every calendar day between the first and last day of activity, so count the days off from the rows — do not try to spot holes in the date column. |

</rules>

<output>

## Report shape

Four parts.

### 1. Daily table

| Date | Day | Active | Typed | First–Last | Prompts |
|---|---|---:|---:|---|---:|

Bold any day over 10 hours. Days that ran past 4am already show it in the First–Last
column, so leave those unbolded.

### 2. Weekly totals

Weeks start Monday. Include how many days of each week had any activity.

### 3. What stands out

Write what can be *read*, rather than restating the table. Useful axes:

- How many days off, and the longest streak without one. Zero days off is itself
  the finding, and the script prints the streak — quote it rather than counting rows.
- The share of hours in the `00-05` bucket. Twelve hours starting at 09:00 and twelve
  starting at 14:00 are not the same life, and the daily table alone cannot tell them
  apart. This is the sharpest burnout signal in the output.
- How many days crossed midnight, or 4am.
- Whether a recovery pattern appears — a short day right after an all-nighter.
- Where the top-3 projects cluster.

### 4. Limits

Attach `<limits>` verbatim.

</output>

<limits>

## What these numbers cannot say

- **Active is closer to a ceiling.** Every gap of 30 minutes or less counts as work, so
  stepping away while Claude runs still counts if the next event lands in time. Tightening
  to 15 minutes usually trims about 10%.
- **Typed is a floor.** It spans only the turns you typed yourself. The real figure is
  between the two.
- **Every run of work is cut short at its end.** A stitched run stops at its last
  event, so the time you spend reading the final answer, or thinking before you close
  the laptop, is never counted. This bias pulls the opposite way from the ceiling
  above, on every block of every day.
- **Work without Claude is invisible.** Meetings, Slack, browser QA, reading code, poking
  at a production database — none of it appears here. Your real hours are certainly
  higher than this table. It is not an attendance record and cannot be used as one.

</limits>

<privacy>

Session logs are read from local disk and nothing leaves the machine. Note that the
"Top 3 projects per day" section prints **directory names — that is, your repo and
worktree names**. Check that section before showing results to anyone else.

</privacy>
