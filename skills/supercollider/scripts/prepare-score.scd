// Infrastructure driver, invoked with argv data, never interpolated source paths.
(
var args = thisProcess.argv, source, final, status, token, frames, rate, channels, seed;
var kind = "source_compile", compiled, function, result, ctx, events, check, encode, quote;
var manifest, file;
source = args[0]; final = args[1]; status = args[2]; token = args[3];
frames = args[4].asInteger; rate = args[5].asInteger;
channels = args[6].asInteger; seed = args[7].asInteger;
check = { |condition, message| if(condition.not) { Error(message).throw } };
quote = { |text|
    var out = "\"";
    text.do { |char|
        var code = char.ascii;
        out = out ++ switch(code,
            34, { "\\\"" }, 92, { "\\\\" }, 10, { "\\n" },
            13, { "\\r" }, 9, { "\\t" },
            { if(code < 32) { "\\u" ++ code.asHexString(4) } { char.asString } });
    };
    out ++ "\""
};
encode = { |value|
    case
    { value.isNil } { "null" }
    { value == true } { "true" }
    { value == false } { "false" }
    { value.isKindOf(String) or: { value.isKindOf(Symbol) } } { quote.value(value.asString) }
    { value.isNumber } { check.value(value.isNaN.not and: { value.abs < inf }, "Nonfinite JSON"); value.asString }
    { value.isKindOf(Dictionary) } {
        "{" ++ value.keys.asArray.sort.collect { |key|
            quote.value(key.asString) ++ ":" ++ encode.value(value[key])
        }.join(",") ++ "}"
    }
    { value.isArray } { "[" ++ value.collect { |item| encode.value(item) }.join(",") ++ "]" }
    { Error("Unsupported manifest value").throw }
};
try {
    compiled = File.readAllString(source).compile;
    check.value(compiled.isKindOf(Function), "Source compilation failed");
    kind = "source_eval";
    function = compiled.value;
    kind = "source_contract";
    check.value(function.isKindOf(Function), "Source must return a Function");
    ctx = (contract: "scs-nrt-source/2", source_path: source,
        source_dir: PathName(source).pathOnly, duration: frames / rate,
        frames: frames, sample_rate: rate, channels: channels,
        format: "wav", sample_format: "int16", seed: seed);
    thisThread.randSeed = seed;
    kind = "source_eval";
    result = function.value(ctx);
    kind = "source_contract";
    check.value(result.isKindOf(Dictionary), "Function must return a structure");
    check.value(result[\contract] == "scs-nrt-source/2", "Source contract 2 required");
    check.value(result[\score].isKindOf(Score), "Native Score required");
    check.value(result[\resources].isArray and: { result[\resources].isEmpty },
        "Only explicit empty resources are supported by this slice");
    check.value(result[\uses].isArray, "Explicit uses array required");
    events = result[\score].score.deepCopy;
    check.value(events.isArray and: { events.notEmpty }, "Nonempty Score required");
    events.do { |bundle|
        check.value(bundle.isArray and: { bundle.size >= 2 }, "Invalid Score bundle");
        check.value(bundle[0].isNumber and: { bundle[0] >= 0 and: { bundle[0] <= ctx[\duration] } }, "Invalid event time");
        bundle.copyToEnd(1).do { |message| check.value(message.isArray, "Invalid Score message") };
    };
    manifest = (contract: "scs-nrt-source/2", resources: [], uses: result[\uses]);
    manifest = encode.value(manifest);
    kind = "score_write";
    Score.write(events, PathName(final).pathOnly +/+ "source.osc", TempoClock.new(1));
    Score.write(events.add([ctx[\duration], [0]]), final, TempoClock.new(1));
    file = File(PathName(final).pathOnly +/+ "source-plan.json", "w");
    check.value(file.isOpen, "Cannot open manifest");
    file.putString(manifest); file.close;
    file = File(status, "w"); check.value(file.isOpen, "Cannot open status");
    file.putString("SC_TOOL\t2\t" ++ token ++ "\tPREPARED\t" ++ frames ++ "\t" ++ rate ++ "\t" ++ channels ++ "\n");
    file.close;
    0.exit;
} { |error|
    error.reportError;
    if(file.notNil) { file.close };
    file = File(status, "w");
    if(file.isOpen) { file.putString("SC_TOOL\t2\t" ++ token ++ "\tERROR\t" ++ kind ++ "\n"); file.close };
    1.exit;
};
)
