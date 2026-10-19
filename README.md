# SCS — Super Collider Skill

A portable Agent Skill for working with [SuperCollider](https://supercollider.github.io/):
writing and debugging `sclang` programs, rendering audio, and checking technical results.

## Status

**Planning stage.** This repository currently contains agreed product requirements
and architecture/development rules. The executable skill and CLI are not implemented yet.

## Planned capabilities

- Diagnose the local SuperCollider environment and search documentation for the installed version.
- Run `sclang` programs with timeouts and explicit success/failure reporting.
- Render WAV files using non-realtime synthesis without a GUI or physical audio device.
- Inspect and validate audio properties, including duration, channels, clipping, and silence.
- Generate diagnostic plots on request and run headless self-tests.
- Later, support managed interactive sessions and extension discovery.

SCS focuses on technical execution, not composition, arrangement, or artistic judgement.
It is intended for Agent Skills-compatible harnesses, with Linux as the initial target.
Rendering requires an explicit NRT input contract; arbitrary realtime scripts are not
automatically convertible. System changes and dependency installation require permission.

## Project documents

- [Product requirements](docs/product/index.md)
- [Architecture and development rules](docs/rules/index.md)

The project documents are currently in Russian. RIS is optional development-workflow
tooling, not a runtime dependency of the planned skill; its installed package and
local tracker database are not included in this repository.

## License

[MIT](LICENSE).
