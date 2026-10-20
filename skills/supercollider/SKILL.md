---
name: supercollider
description: Render a trusted, explicit SuperCollider NRT source to a verified PCM16 WAV and return artifacts and diagnostics. Use for offline SuperCollider rendering or preparing/debugging a source for this render contract. Not for arbitrary realtime scripts, live sessions, music composition, plotting or dependency installation.
---
# SuperCollider NRT render

Use the native SuperCollider engine through this package's render-only CLI.
Resolve all package paths relative to this skill folder, not the caller's cwd.
No OpenCode hooks, RIS, music skill, Remotion, network service or Python packages
are needed. The package is source: `sc-tool` is not an installed shell command.

## Before rendering

1. Read [compatibility](references/compatibility.md) for the exact alpha profile,
   installed dependencies, provenance/security limits and reproducible checks.
   Require Linux x86_64, CPython 3.14.7 and matching installed `sclang`/`scsynth`
   3.14.1 with libsndfile, standard SCClassLibrary and local hard-link support.
   Missing or unsupported components are a diagnostic, not permission to install,
   update or change global configuration. Consult matching local SC HelpSource
   when preparing native SC code; report missing help rather than inventing API.
2. Read the [source contract](references/nrt-contract.md) before writing or
   adapting a source. Start with [minimal-nrt.scd](assets/minimal-nrt.scd).
   The trusted `.scd` must evaluate to a synchronous Function returning native
   Score, `contract: "scs-nrt-source/2"`, explicit `resources` and `uses`.
   Supply SynthDefs and data explicitly; do not inherit realtime server state.
   Declare every possible external Buffer dependency, including computed ones.
3. Confirm permission to execute the source and create outputs/diagnostics.
   **Source is executable and not sandboxed.** Do not execute untrusted code.
   Do not start servers, GUI, network, `play`, `boot` or `recordNRT` in source,
   modify inputs, or convert arbitrary realtime scripts implicitly. The wrapper
   checks declared initial Buffer state, not universal dependency completeness,
   later DSP behavior or artistic quality.
4. Obtain the caller's source, fresh output path, duration, rate and channels.
   Output parent and optional temp/diagnostics base directories must exist.
   Read [CLI parameters and results](references/render-cli.md) before invoking;
   preserve explicit seed and timeout. Never overwrite/delete an existing target
   to make a retry succeed.

## Invoke

Replace paths with actual absolute paths (quote each argument in a shell):

```sh
python3 -B /path/to/supercollider/scripts/sc-tool.py render \
  --source /path/to/supercollider/assets/minimal-nrt.scd \
  --output /existing/directory/new-result.wav \
  --duration 2 --sample-rate 48000 --channels 2 --seed 0 --timeout 120 \
  --diagnostics-dir /existing/diagnostics-directory
```

For a custom source, change `--source` and the requested parameters, not the
packaged fixture. CLI relative paths resolve from the caller's original cwd;
sample paths inside source resolve from its source directory. Pass argv as data,
never interpolate paths into SC code. There are no `doctor`, `docs`, `run`,
`audio`, `self-test` or `session` commands in this delivery.

## Interpret and return

Parse the single compact JSON line (schema 2) and retain the process exit code.
Raw SC streams are in separate diagnostic logs. Report `status`, `stage`,
`exit_code`, requested/effective/measured properties, `artifacts`, diagnostic
directory, errors/warnings and `unfinished_actions`.

Only a successful finalized result with `artifacts.ready` is ready audio.
Code 0, PREPARED, a file or header alone is insufficient. Success includes full
WAV decoding, expected frames/rate/channels, declared resource snapshots,
process cleanup and no-replace publication. For 2 s/48000/stereo the fixture
has 96064 frames (NRT block padding), not 96000; do not trim or pad the result.
See the CLI duration model for requested versus nominal/expected duration.
Record inputs/hashes, seed, versions and measured properties for reproduction;
language seed does not seed random server UGens automatically. No cross-platform
bitwise or musical-quality promise is made.

On error, timeout or cancellation return the failure and retained evidence,
not a guessed cause or a ready partial WAV. Inspect the documented exit table
and logs: repair source/declarations, choose a fresh path, or report a missing
dependency as appropriate. Do not automatically rerun executable source,
extend a timeout or change the system. A published-but-not-ready partial may
survive cleanup failure; preserve it and report its actual state. Never kill
unrelated processes or remove previous diagnostics. Stop after reporting the
artifact/diagnostics; installations, realtime operation and broader validation
require a separate request.
