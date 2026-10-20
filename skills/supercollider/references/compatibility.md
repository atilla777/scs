# Compatibility and reproducible checks

Alpha render-only package. Small native checks and one explicitly activated
Agent Skills smoke were observed in the profile below; these documentation
updates await combined independent review and user publication. Runtime code
uses Python stdlib only; no package manager/network/install/config operation
occurs during render. External programs are not bundled or implementation-copied.
No plotting libraries, Quarks, FFmpeg or mandatory container dependency.
PEP 8 is the Python style source; manual review, stdlib unittest, no project
formatter/linter/build backend/CI installation is claimed.

## Declared alpha profile

- Linux x86_64, Arch/Omarchy; CPython **3.14.7** (`python 3.14.7-1`).
- Matching `sclang` and `scsynth` **3.14.1**, installed Arch
  `supercollider 3.14.1-6`, NRT with `libsndfile 1.2.2-4`.
- Local POSIX filesystem supporting hard links; procfs, Linux child subreaper
  and stdlib pidfd APIs required. Other versions return unsupported environment;
  this is not a claim of tested cross-platform/version support.
- Class library discovery relative to selected sclang installation prefix,
  or `--sc-class-library`; only its standard library is included. Matching
  local HelpSource availability is reported. Runtime always uses private
  HOME/XDG/TMPDIR and a clean child environment with offscreen Qt, without
  inherited GTK/Qt theme overrides or WebEngine sandbox bypass.

Read-only local references used: installed `Score.sc`,
`HelpSource/Classes/Score.schelp`, `Guides/Non-Realtime-Synthesis.schelp`,
`Classes/SoundFile.schelp`, installed `SoundFile.sc`/`File.sc`,
`Reference/Server-Command-Reference.schelp`,
`Reference/Synth-Definition-File-Format.schelp`, and
`/usr/share/doc/supercollider/README_LINUX.md` (standard offscreen operation).
The protocol table/model is tied to official SC commit
`426edf6d8742e1cc3bd85b51ca0c4e595d37a903`, notably
`include/server/SC_OSC_Commands.h`, `server/scsynth/SC_World.cpp`,
`SC_GraphDef.cpp`, `SC_MiscCmds.cpp`; see the accepted feature design for sources.

## Provenance, licenses and bounded security review (2026-10-20)

Read-only `pacman -Qi supercollider libsndfile python`: distribution origins
point to official upstream projects; SuperCollider package signature validated.
libsndfile/Python installed metadata records SHA-256 validation, not a new
signature verification by this tool. SC package licenses GPL-2.0-or-later /
GPL-3.0-or-later (individual notices apply), libsndfile LGPL-2.1-or-later,
CPython PSF-2.0 with bundled notices. Project fixtures/code are original work
under the repository license, not copied server code.

Manual read-only advisory sources:

- <https://security.archlinux.org/package/supercollider>: 3.14.1-6, no listed issues.
- <https://github.com/supercollider/supercollider/security/advisories>: no
  published maintainer advisories displayed.
- <https://security.archlinux.org/package/libsndfile>: historical groups
  AVG-2704/2185 fixed in 1.1.0-1, AVG-1549 in 1.0.31-1; installed 1.2.2-4
  is newer than those listed fixes.
- <https://security.archlinux.org/package/python>: displayed current package
  3.14.8-1 and historical resolved issues; this does not establish security
  equivalence with pinned 3.14.7-1. No automatic update was performed.

These limited public listings are **not a CVE audit**, a scan of all transitive
libraries or assurance that no unreported/new issues exist. Reassess actual
advisories and regression evidence before changing support pins. Trust source
code; do not process untrusted programs under a supposed sandbox guarantee.

## Checks from repository root

Obtain an identified repository revision (record `git rev-parse HEAD` and any
local patch), or retain a content/mode manifest for a copied package. There is
no build step, virtualenv, pip dependency or lockfile to resolve. On Arch,
read-only `pacman -Qi python supercollider libsndfile` records installed versions,
origins, licenses and validation metadata. On another distribution use its
read-only package metadata; matching version strings alone do not establish
support. If components are missing, stop and agree a separate installation
plan using trusted distribution/upstream sources; do not install during render.
For runtime use, keep the entire `supercollider/` folder together, with scripts,
references and assets; no repository-root config or hooks are consulted.
The included [MIT license](../LICENSE) covers this package and its original
fixtures, and must accompany copies; external SC/system libraries retain their
own licenses and are not bundled.

```sh
python3 -B -m unittest discover -s tests/unit -v
python3 -B -m unittest discover -s tests/contract -v
```

Before opting into native integration, check the runner below is available and
really has distinct PID/network namespaces, no GUI env, no visible realtime
server, empty audio devices and no external route. Do not use an inherited
desktop/audio environment or bypass a failed isolation prerequisite. Use a
fresh caller-owned directory for HOME/XDG/TMP and optional retained evidence;
create its subdirectories before this command. Replace `/owned/check/` paths:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  HOME=/owned/check/home XDG_CONFIG_HOME=/owned/check/config \
  XDG_DATA_HOME=/owned/check/data XDG_CACHE_HOME=/owned/check/cache \
  XDG_RUNTIME_DIR=/owned/check/runtime TMPDIR=/owned/check/tmp \
  SCS_EVIDENCE_DIR=/owned/check/evidence SCS_REAL_TESTS=1 \
  python3 -B -m unittest discover -s tests/integration -v
```

The real integration test additionally uses an **already available** `bwrap`
runner, not a runtime dependency. It unshares network and PID namespaces,
mounts host read-only, uses private procfs/dev with empty `/dev/snd`, exposes
only its temporary test directory writable, and runs CLI with no GUI session
environment or visible host realtime server. No virtual display or browser
sandbox disabling. Real tests skip unless explicitly opted in; skip is not pass.
The minimal fixture is original MIT, 480 Hz/0.1/2 s/48 kHz/stereo. Oracle:
96064 decoded frames, channel RMS 0.1/√2 ±0.002 over 0.1–1.9 s; 480 Hz
sine/cosine projection amplitude 0.1 ±0.002. Fixed seed repeat RMSE ≤2/32768
on the same environment; no cross-platform bitwise promise.

Contract tests isolate external executable behavior with small original fake
SC processes plus independent binary fixtures. They do not certify the SC
engine. Pure tests cover timing, binary boundaries, full PCM16/float32 decoding,
generation/use lifetimes, no-replace publication and process cleanup. Real
resource tests use original nonuniform float32/PCM16 fixtures, file ranges and
channel reorder/repetition, data/zero, scheduled bufnum reuse, native DSP mutation
and actual server failure with a normal main WAV. Initial snapshots are compared
completely; zero input does not prove internal call history. Contract tests model
silent allocation failure without host OOM, missing/truncated/wrong/stale evidence,
short preparation files and forbidden commands. Models do not certify SC behavior.
Integrated resilience checks exercise both empty and nonempty resource branches:
stage-boundary faults and latched SIGINT/SIGTERM, deadlines inside Score,
canonical/reference, snapshot and main-audio reads, publication/final-evidence
failures, protected aliases, and concurrent empty/resource success plus NRT
failure at one target. Process checks include detached descendants after leader
exit, TERM-to-KILL escalation, foreign-control survival and both stream limits.
Injected boundary faults/callbacks are contract models, not kernel/SC fault
certification; actual subprocess signals/timeouts and real SC suites complement
them. Set `SCS_EVIDENCE_DIR` to a caller-owned directory to retain per-run
contract-matrix and real-SC diagnostics (including JSON and separate streams).
Evidence copies preserve original temporary paths; those paths may no longer
exist after the test, so inspect the retained run-ID directory instead.
The suites exercise actual small native renders in the declared profile.
The actual 1000-second high-rate render remains **NOT RUN / UNVERIFIED**;
only its pure timing oracle is checked. Full feature acceptance is not claimed.

## Observed Agent Skills smoke (2026-10-20)

One separately authorized explicit-activation scenario passed with **OpenCode
v2.0.32**, native `skill({"id":"supercollider"})`, build agent and CLI default
model **opencode/minimax-m3.1-flash-free** (no model switch). A clean test copy
contained this complete skill folder under `.opencode/skills/supercollider/`.
The agent loaded the skill, read its references and fixture, then invoked one
2s/48000/stereo/seed-0 render with timeout 60 through an evidence-only isolation
prefix. Total harness time was 50.175 seconds, below the agreed 300-second limit;
there was no second render, hook, music skill, Remotion or installation.

SC execution had private network/PID namespaces, private proc/dev without audio,
read-only host and caller-owned writable output/HOME/XDG/TMP. The namespace
witness found no GUI session, realtime SC process or external route. The LLM
provider used its ordinary network connection: an offline LLM is **not** claimed.
The CLI returned success/complete/exit 0 with one ready artifact and no errors or
unfinished actions. Independent full WAV decoding measured PCM16, 96064 frames,
48000 Hz and 2 channels; the documented RMS/projection oracles passed.

The WAV **file** SHA-256 was
`eb803d72c59dea95c8dd4b11bb2f7f5ec735f4768d73de4ec3acb68dfdeef552`.
The decoded **PCM payload** SHA-256 was
`d0c3d295066a8c234c0a3d6d2be1adc397fd30863536efd3ab34231ec21f03e5`.
The test agent incorrectly called the first value a PCM hash in its prose;
these are distinct measurements, not a new cross-platform bitwise oracle.
Four known nonfatal scheduling-priority warnings were retained. Three unrelated
`ls` attempts were denied by test permissions and did not execute. Therefore
this observation does not establish flawless instruction following, autonomous
routing, repeatability, general model reliability or all-client compatibility.

The smoke exercised repository revision
`539b66723fee1d37b0e4d1eb3b0648e5f82eefb7` before this factual documentation
update. Runtime, SKILL entrypoint and fixture are unchanged; no new live-agent
run is inferred for changed documentation bytes. When obtained as a repository,
see `docs/specs/nrt-render/verification.md` for the compact revision-bound record
and reproduction procedure. That project report is not a runtime requirement:
this whole skill folder remains independently copyable.
