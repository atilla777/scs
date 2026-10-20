# SCS — Super Collider Skill

A portable Agent Skill for offline [SuperCollider](https://supercollider.github.io/)
rendering: explicit NRT source → verified PCM16 WAV and structured diagnostics.

## Status

**Alpha render-only source package.** Small native NRT checks and one explicitly
activated Agent Skills smoke passed in the recorded Linux environment. OpenCode
v2.0.32 loaded the skill through its native `skill` tool and the agent rendered
the packaged two-second example. This is not a reliability, autonomous-routing
or cross-client support claim. Full feature acceptance is not claimed; the real
1000-second high-rate render remains NOT RUN. See the compact
[verification record](docs/specs/nrt-render/verification.md) for revisions,
commands, cases and limits. These evidence/documentation updates await combined
independent review and user publication.

## Use

Obtain this repository at an identified revision, or copy the complete
[`skills/supercollider/`](skills/supercollider/SKILL.md) folder unchanged to a
location your Agent Skills-compatible harness can discover. No build or Python
package installation is required; harness discovery is client-specific. One
OpenCode explicit-activation scenario was observed, not every discovery/routing
path. Start with **[SKILL.md](skills/supercollider/SKILL.md)**.

The CLI can also be invoked directly from any cwd:

```sh
python3 -B /path/to/skills/supercollider/scripts/sc-tool.py render \
  --source /path/to/skills/supercollider/assets/minimal-nrt.scd \
  --output /existing/directory/new-result.wav \
  --duration 2 --sample-rate 48000 --channels 2 --seed 0 --timeout 120
```

Dependencies must already be installed: Linux x86_64, CPython 3.14.7,
matching SuperCollider 3.14.1 tools with libsndfile and standard class library,
and a local filesystem with hard links. See [compatibility, provenance and
checks](skills/supercollider/references/compatibility.md) for exact packages,
read-only discovery and clean-run instructions; installation is a separately
authorized system operation, not part of render.

Read the [source contract](skills/supercollider/references/nrt-contract.md)
and [CLI reference](skills/supercollider/references/render-cli.md). Only
`artifacts.ready` in a successful finalized JSON result identifies ready audio;
raw process output is retained separately. Existing targets are never overwritten.
Source is trusted executable code, **not sandboxed**.

SCS focuses on technical execution, not composition, arrangement, or artistic judgement.
It is intended for Agent Skills-compatible harnesses, with Linux as the initial target.
Rendering requires an explicit NRT input contract; arbitrary realtime scripts are not
automatically convertible. There are no standalone doctor/docs/run/audio/plot/
self-test/session commands. No clipping, silence, musical-quality or universal
resource/dependency verification is promised. System changes require permission.

## Project documents

- [Product requirements](docs/product/index.md)
- [Architecture and development rules](docs/rules/index.md)

The project documents are currently in Russian. RIS is optional development-workflow
tooling, not a runtime dependency of the skill; its installed package and
local tracker database are not included in this repository.

## License

[MIT](LICENSE).
