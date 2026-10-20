// Infrastructure driver, invoked with argv data, never interpolated source paths.
(
var args = thisProcess.argv, source, final, status, token, frames, rate, channels, seed;
var kind = "source_compile", compiled, function, result, ctx, events, check, encode, quote;
var manifest, file, resources, schedule, staged, prepareResource, validInt;
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
    { value.isNumber } { check.value(value.isNaN.not and: { value.abs < inf }, "Nonfinite JSON"); if(value.isKindOf(Float)) { value.asStringPrec(17) } { value.asString } }
    { value.isKindOf(Dictionary) } {
        var keys = value.keys.asArray;
        if(value[\prepared].notNil and: { keys.includes(\retire).not }) { keys = keys.add(\retire) };
        if(value[\kind] == "file") {
            [\frames, \channels].do { |key| if(keys.includes(key).not) { keys = keys.add(key) } };
        };
        "{" ++ keys.sort.collect { |key|
            quote.value(key.asString) ++ ":" ++ encode.value(value[key])
        }.join(",") ++ "}"
    }
    { value.isArray } { "[" ++ value.collect { |item| encode.value(item) }.join(",") ++ "]" }
    { Error("Unsupported manifest value").throw }
};
validInt = { |value| value.isKindOf(Integer) and: { value > 0 } };
staged = List.new;
prepareResource = { |declaration, index|
    var initial, p, base, input, original, beforeSize, beforeTime, reader, writer, reference;
    var count, chans, sampleRate, selection, first, wanted, total, position, chunk, selected, emit, inputFile, stagedFile;
    kind = "source_contract";
    check.value(declaration.isKindOf(Dictionary), "Generation structure required");
    check.value((declaration.keys.asSet - Set[\retire]) == Set[\id, \bufnum, \at, \initial], "Generation keys");
    check.value(declaration[\id].isString, "Generation ID must be a String");
    initial = declaration[\initial];
    check.value(initial.isKindOf(Dictionary), "Initial structure required");
    check.value(["file", "data", "zero"].includesEqual(initial[\kind]), "Unsupported initial mode");
    base = PathName(final).pathOnly +/+ ("resource-" ++ index);
    p = (canonical: base ++ ".canonical.wav", reference: base ++ ".reference.f32", snapshot: base ++ ".snapshot.wav");
    if(initial[\kind] == "file") {
        check.value(initial.keys.every { |key| [\kind, \path, \start_frame, \frames, \channels].includes(key) }, "File initial keys");
        check.value(initial[\path].isString and: { initial[\path].notEmpty }, "Resource path required");
        original = initial[\path];
        if(original[0] != $/) { original = ctx[\source_dir] +/+ original };
        original = File.realpath(original);
        check.value(original.notNil and: { File.type(original) == \regular }, "Regular input required");
        beforeSize = File.fileSize(original); beforeTime = File.mtime(original);
        input = base ++ ".input";
        // File.copy preserves the input's mode, so create private bytes instead.
        inputFile = File(original, "rb"); stagedFile = File(input, "wb");
        check.value(inputFile.isOpen and: { stagedFile.isOpen }, "Cannot stage input");
        protect {
            position = 0.0;
            while { position < beforeSize } {
                var n = (beforeSize - position).min(65536).asInteger;
                chunk = Int8Array.newClear(n); inputFile.read(chunk);
                check.value(chunk.size == n, "Short source byte read");
                stagedFile.write(chunk); position = position + n;
            };
        } { inputFile.close; stagedFile.close };
        check.value(File.fileSize(input) == beforeSize and: { File.fileSize(original) == beforeSize }
            and: { File.mtime(original) == beforeTime }, "Source changed or short copy");
        staged.add((original: original, staged: input, size: beforeSize, mtime: beforeTime));
        reader = SoundFile.new;
        check.value(reader.openRead(input), "Cannot decode resource");
        total = reader.numFrames; chans = reader.numChannels; sampleRate = reader.sampleRate;
        check.value(sampleRate == sampleRate.asInteger, "Noninteger source rate");
        sampleRate = sampleRate.asInteger;
        first = initial[\start_frame] ? 0;
        wanted = initial[\frames] ? (total - first);
        selection = initial[\channels] ? (0 .. (chans - 1));
        check.value(first.isKindOf(Integer) and: { first >= 0 } and: { validInt.value(wanted) }
            and: { first.asFloat + wanted <= total } and: { selection.isArray and: { selection.notEmpty } }
            and: { selection.every { |c| c.isKindOf(Integer) and: { c >= 0 and: { c < chans } } } }, "Invalid file range/channels");
        initial = (kind: "file", path: original, start_frame: first, frames: initial[\frames], channels: initial[\channels]);
        count = wanted;
    } {
        check.value(initial.keys.asSet == if(initial[\kind] == "data") {
            Set[\kind, \frames, \channels, \sample_rate, \samples]
        } { Set[\kind, \frames, \channels, \sample_rate] }, "Initial keys");
        count = initial[\frames]; chans = initial[\channels]; sampleRate = initial[\sample_rate];
        check.value(validInt.value(count) and: { validInt.value(chans) } and: { chans <= 16383 }, "Invalid resource dimensions");
        selection = (0 .. (chans - 1));
        if(initial[\kind] == "data") {
            check.value(initial[\samples].isKindOf(FloatArray) and: { initial[\samples].size == (count * chans) }, "FloatArray count required");
        };
    };
    check.value(validInt.value(sampleRate) and: { sampleRate <= 16777216 }
        and: { (selection.size.asFloat * 4) <= 65535 } and: { (count.asFloat * selection.size) <= 2147483647 }
        and: { ((count.asFloat * selection.size * 4) + 4096) <= 4294967295.0 }, "Unrepresentable resource");
    p.putAll((frames: count, channels: selection.size, sample_rate: sampleRate));
    kind = "resource_prepare";
    writer = SoundFile.new.headerFormat_("WAV").sampleFormat_("float").sampleRate_(sampleRate).numChannels_(selection.size);
    check.value(writer.openWrite(p[\canonical]), "Cannot write canonical");
    reference = File(p[\reference], "wb");
    check.value(reference.isOpen, "Cannot write reference");
    emit = { |values|
        kind = "source_contract";
        check.value(values.every { |x| x.isNaN.not and: { x.abs < inf } }, "Nonfinite initial sample");
        kind = "resource_prepare";
        reference.writeLE(values); writer.writeData(values);
    };
    protect {
        position = 0;
        if(initial[\kind] == "file") {
            while { position < total } {
                var n = (total - position).min(8192), lower, upper;
                chunk = FloatArray.newClear(n * chans);
                reader.readData(chunk);
                check.value(chunk.size == (n * chans), "Short source read");
                lower = first.max(position); upper = (first + count).min(position + n);
                if(upper > lower) {
                    selected = FloatArray.newClear((upper - lower) * selection.size);
                    (upper - lower).do { |frame|
                        selection.do { |channel, ci| selected[(frame * selection.size) + ci] = chunk[((lower - position + frame) * chans) + channel] };
                    };
                    emit.value(selected);
                };
                position = position + n;
            };
            chunk = FloatArray.newClear(chans); reader.readData(chunk);
            check.value(chunk.size == 0, "Extra source samples");
            check.value(File.fileSize(original) == beforeSize and: { File.mtime(original) == beforeTime }, "Source changed");
        } {
            while { position < count } {
                var n = (count - position).min(8192);
                selected = if(initial[\kind] == "zero") { FloatArray.newClear(n * chans) } {
                    initial[\samples].copyRange(position * chans, ((position + n) * chans) - 1)
                };
                emit.value(selected); position = position + n;
            };
        };
    } { writer.close; reference.close; if(reader.notNil) { reader.close } };
    (id: declaration[\id], bufnum: declaration[\bufnum], at: declaration[\at], retire: declaration[\retire], initial: initial, prepared: p)
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
    check.value(result[\resources].isArray, "Explicit resources array required");
    check.value(result[\uses].isArray, "Explicit uses array required");
    result[\uses].do { |use|
        check.value(use.isKindOf(Dictionary) and: { use[\resources].isArray }
            and: { use[\resources].every { |id| id.isString } }, "Use resource IDs must be Strings");
    };
    events = result[\score].score.deepCopy;
    check.value(events.isArray and: { events.notEmpty }, "Nonempty Score required");
    events.do { |bundle|
        check.value(bundle.isArray and: { bundle.size >= 2 }, "Invalid Score bundle");
        check.value(bundle[0].isNumber and: { bundle[0] >= 0 and: { bundle[0] <= ctx[\duration] } }, "Invalid event time");
        bundle.copyToEnd(1).do { |message| check.value(message.isArray, "Invalid Score message") };
    };
    kind = "resource_prepare";
    resources = result[\resources].collect { |declaration, index| prepareResource.value(declaration, index) };
    schedule = List.new;
    resources.do { |g, index|
        var p = g[\prepared], b = g[\bufnum], init;
        init = if(g[\initial][\kind] == "zero") {
            [\b_alloc, b, p[\frames], p[\channels], 0, p[\sample_rate]]
        } { [\b_allocRead, b, p[\canonical], 0, -1] };
        schedule.add([g[\at], 1, index * 3, [\b_free, b]]);
        schedule.add([g[\at], 1, (index * 3) + 1, init]);
        schedule.add([g[\at], 1, (index * 3) + 2, [\b_write, b, p[\snapshot], "WAV", "float", -1, 0, 0]]);
        if(g[\retire].notNil) { schedule.add([g[\retire], 0, index, [\b_free, b]]) };
    };
    events.do { |bundle, bi| bundle.copyToEnd(1).do { |message, mi|
        schedule.add([bundle[0], 2, (bi * 2147483648.0) + mi, message]);
    } };
    schedule.add([ctx[\duration], 3, 0, [0]]);
    schedule = schedule.asArray.sort { |a, b|
        if(a[0] == b[0]) { if(a[1] == b[1]) { a[2] < b[2] } { a[1] < b[1] } } { a[0] < b[0] }
    }.collect { |item| [item[0], item[3]] };
    manifest = (contract: "scs-nrt-source/2", resources: resources, uses: result[\uses], staged_inputs: staged.asArray);
    manifest = encode.value(manifest);
    kind = "score_write";
    Score.write(events, PathName(final).pathOnly +/+ "source.osc", TempoClock.new(1));
    Score.write(schedule, final, TempoClock.new(1));
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
