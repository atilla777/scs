# Source contract `scs-nrt-source/2`

This task-branch implementation, pending integration and independent review,
supports explicit external Buffer generations as well as empty resources.
Agent Skills release remains separate. No fallback to source contract 1.

A trusted `.scd` evaluates to one Function. It synchronously receives context
and returns a Dictionary/Event with `contract: "scs-nrt-source/2"`, a native
`Score`, explicit `resources: [...]` and explicit `uses: [...]`.
The [minimal fixture](../assets/minimal-nrt.scd) is an original MIT example.

Context keys: `contract`, `source_path`, `source_dir`, `duration` (nominal N/R),
`frames` (N), `sample_rate`, `channels`, `format: "wav"`,
`sample_format: "int16"`, `seed`. No user output path is passed to source.
Language random seed is set before the single Function invocation. Random
server UGens need explicit native seeding in the user's graph.

Every `/s_new` or `/s_newargs` needs a `uses` declaration:

```supercollider
(anchor: [2, 0], from: 0.01, through: ctx[\duration], resources: [])
```

Anchor indices refer to actual returned `score.score`: zero-based bundle index
and message index excluding timestamp. `Score` inserts a default group, so use
the actual array, not just the list originally passed to its constructor.
The anchor must identify a synth creation. All intervals are finite and lie
within nominal duration. At least one interval for each creation anchor must
cover its creation; subsequent intervals for that same anchor may start later
(for example `[0.01, 1.0]` followed by `[1.0, 2.0]`, both with `resources: []`).
Creation coverage is checked across declarations, independently of their order,
not required in every individual interval. Declare all possible external Buffer dependencies, including
those controlled/mapped/computed or read during node termination. Each use lists
generation IDs, including explicit `[]` for nodes with no external dependencies.
Native LocalBuf/internal DSP is not prohibited or claimed universally verified.

`dependency_coverage: "trusted-declared"`, `dependencies_inferred: false` is
always explicit. No static inference or proof of author truthfulness is claimed.
The author must not use undeclared realtime resources, start processes,
servers, GUI or network, call `recordNRT`/`play`/`boot`, write user output,
modify inputs, or rely on asynchronous callbacks during preparation.
Trusted executable source is not made safe by these checks; it is not a sandbox.

## External Buffer generations

Each declaration has `id` (unique ASCII String `[A-Za-z0-9_-]{1,64}`),
`bufnum` (integer 0–1023), `at`, `retire` (nil or strictly later than `at`),
and `initial`. Times are finite, nonnegative, at most `ctx[\duration]`.
SC Event omits nil values internally; an absent `retire` means nil.

Initial forms (String `kind`, not Symbol):

```supercollider
(kind: "file", path: "samples/input.wav", start_frame: 0, frames: nil, channels: [1, 0, 1])
(kind: "data", frames: 3, channels: 2, sample_rate: 32000,
    samples: FloatArray[0.125, -0.25, 0.375, -0.5, 0.625, -0.75])
(kind: "zero", frames: 3, channels: 2, sample_rate: 22050)
```

File paths are relative to `ctx[\source_dir]`, not process cwd. `start_frame`
defaults to 0; nil/omitted frames means through EOF, and nil/omitted channels
means all channels. Channel reorder/repetition is supported. The entire range
must exist: no clamp/padding. Inputs are privately staged, checked for stability
and decoded with SC SoundFile using actual read counts, without modifying inputs.

Frames/channels/rate are positive integers, frames×channels ≤ 2^31−1,
4×channels ≤ 65535, rate ≤ 2^24. Float32 WAV data plus 4096 bytes must fit
RIFF. Data is interleaved FloatArray with exactly frames×channels finite samples.
NaN/Inf is invalid. No resampling or gain transformation.

Scheduled generations and bufnum reuse require disjoint nominal and real
NRT-block lifetimes. Uses cannot precede initialization; the last usage block
must be strictly before retirement's block. Distinct timestamps within a block
do not make overlapping usage safe. Block mapping uses the same
[q/T model](render-cli.md#duration) as output duration.

Order: retirement → initialization and immediate snapshot for each generation
in declaration order → original user messages → terminal marker. The driver
frees old state, initializes from canonical float32 data (or zero allocation),
and snapshots the actual Buffer **in the same NRT**, before consumer commands/DSP.
CLI completely decodes reference/canonical before NRT and snapshots afterward,
comparing every float32 value exactly (±0 equal, no epsilon). A good main WAV
and exit 0 cannot compensate for missing, stale, truncated, wrong-channel or
wrong-sample evidence. No per-generation NRT rerun.

This proves **initial state readiness**, not internal call history, later DSP
reads/writes or arbitrary UGen allocations. Declared intentional DSP mutation
is supported but not certified by the initial snapshot. Raw Buffer setup,
reload/free, streaming handles/leaveOpen, `/b_gen`, `/b_set[n]`, opaque commands
and hidden completion programs are unsupported, not silently converted.

## Native Score boundary

Allowed infrastructure commands (not an artistic UGen whitelist):

```text
/d_recv /d_free /s_new /s_newargs
/n_free /n_run /n_set /n_setn /n_fill /n_map /n_mapn /n_mapa /n_mapan
/n_before /n_after /n_order
/g_new /g_head /g_tail /g_freeAll /g_deepFree
/c_set /c_setn /c_fill
cmd_none (numeric opcode 0)
```

Pinned numeric opcodes normalize to the same command checks. Binary enforcement
checks OSC framing, lengths, alignment, argument shapes, finite timestamps,
monotonic event order and full byte consumption. `/d_recv` contains only a
structurally checked SCgf v1/v2 SynthDef blob; absent completion or integer-zero
placeholder is accepted. SCgf counts, controls, UGen connections and variants
are bounds-checked without a UGen whitelist. SynthDefs/variants must be
available from preceding `/d_recv`, accounting for `/d_free`.

Nested bundles, arbitrary blobs/completions, trailing arguments, raw `/b_*`,
plugin/opaque commands, `/quit`, scheduler clearing and unsupported commands
fail before execution. SC 3.14.1 can leave blob **alignment** bytes nonzero;
their length/bounds are checked but they are not interpreted as payload or an
extra OSC program. All source message bytes must still match the final Score.
The final Score preserves every source message byte and original user ordering,
adding only manifest-matching Buffer instrumentation and a terminal no-op after
all user messages at nominal duration. Generated commands and this run's
adapter-assigned paths are checked before NRT.

Driver uses native `Score.write` at tempo 1. Exact token-bound PREPARED status,
normal exit, no observed errors and full binary/anchor correspondence are all
required. PREPARED confirms neither NRT completion nor audio validity.
`scsynth -N` runs from a fresh Score with `-D 0` and no streaming input; no
preloaded user SynthDefs or realtime state is inherited.
