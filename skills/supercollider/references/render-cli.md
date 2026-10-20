# Render CLI — empty-resource baseline

These instructions accompany the task-branch implementation, pending integration.
Only `render` is implemented; Agent Skills packaging is a later task.

From any working directory (replace paths with your own):

```sh
python3 -B /path/to/skills/supercollider/scripts/sc-tool.py render \
  --source /path/to/skills/supercollider/assets/minimal-nrt.scd \
  --output /existing/directory/new-result.wav \
  --duration 2 --sample-rate 48000 --channels 2
```

The source is executed once, synchronously. It is trusted executable code,
**not sandboxed**. Read the [source contract](nrt-contract.md) first.

## Parameters

Required: `--source`, `--output`, `--duration`, `--sample-rate`, `--channels`.
Optional: `--format wav`, `--seed 0`, `--timeout 120`, `--sclang PATH`,
`--scsynth PATH`, `--sc-class-library PATH`, `--temp-dir EXISTING_DIRECTORY`,
`--diagnostics-dir EXISTING_DIRECTORY`, `--json`.

- Decimal duration: finite, positive, at most 86400 s; half-up rounded target
  frames must be at least one. Rate: integer 8000–192000; channels: 1–32.
- Seed: integer 0–2147483647; timeout: integer 1–86400 s.
- WAV PCM16 only. RF64 is not supported. Size is checked against RIFF limits
  using the expected NRT block count plus a 4096-byte header reserve.
- Unknown, duplicate, missing and invalid parameters fail; `--flag=value` is
  also supported. No shell expansion (including `~`). Relative paths start
  at the caller's original working directory. Quote paths in your shell.
- Executables: explicit path, otherwise discovery on the caller's PATH.
  Child environments do not inherit SC/Qt/GTK overrides or user extensions.
- Output parent and optional base directories must exist. No overwrite flag:
  choose a fresh output path. Existing files, symlinks (including dangling
  ones) and hardlink aliases are protected. Publication uses an atomic hard
  link, never truncation or a copy fallback.

## Results and diagnosis

One compact UTF-8 JSON line, schema 2, is emitted after finalization. Raw SC
stdout/stderr are separate retained log files. Inspect `status`, `stage`,
`errors`, `warnings`, `requested`, `effective`, `measured`, `resource_evidence`,
`artifacts`, `diagnostics` and `unfinished_actions`; process exit status agrees
with `exit_code`. Unknown properties are null.

Only `artifacts.ready` denotes a ready result. An exit code, PREPARED record,
file existence or suitable header alone is not success. Success requires
confirmed source/Score preparation, normal NRT completion, complete clean log
evidence, explicit zero/zero resource evidence, full WAV decoding and matching
properties, owned-process cleanup, safe publication and file finalization.

| Exit | Outcome |
|---:|---|
| 0 | success |
| 2 | invalid input / unsupported source contract |
| 3 | missing/non-executable dependency or unsupported environment |
| 10 | sclang error / unconfirmed preparation |
| 11 | NRT error / unknown substantial NRT diagnostic |
| 12 | absent, malformed or incomplete WAV |
| 13 | valid WAV with mismatched rate/channels/frames |
| 14 | file error / protected existing output |
| 20 | wrapper failure |
| 21 | resource limit (16 MiB per stream/stage) |
| 24 | overall monotonic deadline exceeded |
| 25 | cleanup/evidence finalization failure (original cause retained) |
| 130 / 143 | SIGINT / SIGTERM cancellation |

Diagnostics are retained in a new mode-0700 directory; location is always
reported. Files are private (0600). Select `--diagnostics-dir` for durable
retention; system temp may be removed by the OS. Logs, status, source/final
Score, source declarations, hashes, measurements, versions and file-role
manifest are retained. Private HOME/XDG/TMPDIR work is disposable.
On failure a useful partial WAV is retained in its private output-FS staging
directory, never marked ready. If publication succeeded before cleanup failed
or cancellation arrived, output is `published=true, verified=true` in partial,
not ready, and the user's published path is not deleted automatically.

Deadline covers discovery (each version probe max 2 s), preparation, NRT and
audio verification. Cleanup has a separate shared 5 s budget. Only owned
children/adopted descendants are signalled through pidfds and reaped; no
process-name killing. SIGKILL of the CLI, OS failure, kernel-uninterruptible
tasks or hostile source behavior are not guaranteed cleanup scenarios.

## Duration

For requested Decimal D and rate R, N = ROUND_HALF_UP(D×R). Source context
duration is N/R. The terminal 32.32 OSC timestamp T is checked within one tick
of N×2^32/R. For SC 3.14.1, B=64, q=floor(B×2^32/R), expected frames are
B×max(1,ceil(T/q)). WAV must match exactly: no trim, padding or ±1 tolerance.
JSON reports requested, nominal, expected and measured durations separately.
Examples: 48000/2 → 96064 frames; 192000/1000 → 192000128.

See [compatibility and checks](compatibility.md) for the exact supported profile
and headless verification command.
