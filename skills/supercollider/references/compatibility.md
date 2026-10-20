# Compatibility and reproducible checks

Task-branch baseline, pending integration and independent review. Runtime code
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
The suites exercise actual small native renders in the declared profile;
full feature acceptance additionally requires AC-016's separately agreed
Agent Skills harness scenario. Static metadata/link checks do not prove that
behavior. No harness run or full feature acceptance is claimed here.
The actual 1000-second high-rate render was not authorized/run; only its pure
timing oracle is checked. No Agent Skills harness cost/behavior claim is made.
