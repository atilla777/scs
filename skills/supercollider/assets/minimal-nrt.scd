// Own MIT fixture: 480 Hz, amplitude 0.1, explicit empty external dependencies.
{ |ctx|
    var score = Score([
        [0.0, [\d_recv, SynthDef(\scsMinimal, {
            Out.ar(0, Array.fill(ctx[\channels], { SinOsc.ar(480, 0, 0.1) }))
        }).asBytes]],
        [0.01, [\s_new, \scsMinimal, 1000, 0, 1]]
    ]);
    (
        contract: "scs-nrt-source/2",
        score: score,
        resources: [],
        uses: [(anchor: [2, 0], from: 0.01, through: ctx[\duration], resources: [])]
    )
}
