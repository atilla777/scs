# Source contract `scs-nrt-source/2`

The current task-branch baseline supports **explicit empty external resources**
only. Nonempty Buffer-generation declarations produce `source_contract` before
NRT; they are not silently ignored. Buffer generation support and Agent Skills
release are separate tasks. No fallback to source contract 1.

A trusted `.scd` evaluates to one Function. It synchronously receives context
and returns a Dictionary/Event with `contract: "scs-nrt-source/2"`, a native
`Score`, explicit `resources: []` and explicit `uses: [...]`.
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
those controlled/mapped/computed or read during node termination. This baseline
therefore accepts only nodes with **no external Buffer dependencies**.
Native LocalBuf/internal DSP is not prohibited or claimed universally verified.

`dependency_coverage: "trusted-declared"`, `dependencies_inferred: false` is
always explicit. No static inference or proof of author truthfulness is claimed.
The author must not use undeclared realtime resources, start processes,
servers, GUI or network, call `recordNRT`/`play`/`boot`, write user output,
modify inputs, or rely on asynchronous callbacks during preparation.
Trusted executable source is not made safe by these checks; it is not a sandbox.

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
The final Score contains exactly those source bundles, then a terminal no-op
after all user messages, at nominal duration.

Driver uses native `Score.write` at tempo 1. Exact token-bound PREPARED status,
normal exit, no observed errors and full binary/anchor correspondence are all
required. PREPARED confirms neither NRT completion nor audio validity.
`scsynth -N` runs from a fresh Score with `-D 0` and no streaming input; no
preloaded user SynthDefs or realtime state is inherited.
