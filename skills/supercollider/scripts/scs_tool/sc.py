"""SuperCollider boundary, binary Score checks and adapters."""

import hashlib
import json
import math
import os
import re
import shutil
import struct
import time
from pathlib import Path


class Failure(Exception):
    def __init__(self, code, exit_code, message, details=None):
        super().__init__(message)
        self.code, self.exit_code, self.details = code, exit_code, details


def read_file(path, checkpoint=lambda: None):
    with open(path, "rb") as stream:
        chunks = []
        while block := stream.read(65536):
            checkpoint()
            chunks.append(block)
        return b"".join(chunks)


def discover(request, owner, directory, env, deadline, checkpoint):
    binaries, versions = {}, {}
    for name in ["sclang", "scsynth"]:
        binary = request.get(name) or shutil.which(name)
        if not binary or not Path(binary).exists():
            raise Failure(
                "dependency_missing", 3, name + " not found; provide --" + name
            )
        if not Path(binary).is_file() or not os.access(binary, os.X_OK):
            raise Failure("dependency_unexecutable", 3, name + " is not executable")
        binaries[name] = str(Path(binary).resolve())
        try:
            evidence = owner.run(
                [binaries[name], "-v"],
                directory,
                name + "-version",
                min(deadline, time.monotonic() + 2),
                env,
                checkpoint,
            )
        except OSError as exc:
            raise Failure("dependency_unexecutable", 3, str(exc)) from exc
        output = (
            read_file(evidence["stdout"], checkpoint)
            + read_file(evidence["stderr"], checkpoint)
        ).decode("utf-8", "replace")
        if evidence["returncode"] != 0 or not re.fullmatch(
            re.escape(name) + r" 3\.14\.1 \(Built from .*\)\s*", output
        ):
            raise Failure(
                "unsupported_environment",
                3,
                "Expected " + name + " 3.14.1",
                {"observed": output},
            )
        versions[name] = "3.14.1"
    library = request.get("sc_class_library")
    if not library:
        prefix = Path(binaries["sclang"]).parent.parent
        candidates = [prefix / "share/SuperCollider/SCClassLibrary"]
        library = next((str(p) for p in candidates if p.is_dir()), None)
    if not library or not (Path(library) / "Common/Control/Score.sc").is_file():
        raise Failure(
            "unsupported_environment", 3, "Provide matching --sc-class-library"
        )
    binaries["class_library"] = str(Path(library).resolve())
    help_path = Path(library).parent / "HelpSource"
    versions["local_help"] = str(help_path) if help_path.is_dir() else None
    return binaries, versions


def prepare_score(
    request, owner, directory, env, binaries, deadline, token, checkpoint
):
    from .files import write_json, write_text

    config = directory / "sclang-conf.yaml"
    write_text(
        config,
        "includePaths: ["
        + json.dumps(binaries["class_library"])
        + "]\nexcludePaths: []\npostInlineWarnings: false\n",
    )
    final, status = directory / "score.osc", directory / "status.txt"
    driver = Path(__file__).resolve().parent.parent / "prepare-score.scd"
    evidence = owner.run(
        [
            binaries["sclang"],
            "-D",
            "-a",
            "-l",
            config,
            "--include-path",
            binaries["class_library"],
            driver,
            request["source"],
            final,
            status,
            token,
            request["target_frames"],
            request["sample_rate"],
            request["channels"],
            request["seed"],
        ],
        directory,
        "prepare",
        deadline,
        env,
        checkpoint,
    )
    try:
        record = read_file(status, checkpoint).decode("ascii")
    except (OSError, UnicodeError):
        record = ""
    prefix = "SC_TOOL\t2\t" + token + "\t"
    error = re.fullmatch(
        re.escape(prefix)
        + r"ERROR\t(source_compile|source_eval|source_contract|resource_prepare|score_write)\n",
        record,
    )
    if error:
        kind = error.group(1)
        raise Failure(
            "source_contract" if kind == "source_contract" else "sclang_error",
            2 if kind == "source_contract" else 10,
            "Preparation failed: " + kind,
            {"kind": kind, "process": evidence},
        )
    expected = (
        prefix
        + "PREPARED\t"
        + "\t".join(
            str(request[k]) for k in ["target_frames", "sample_rate", "channels"]
        )
        + "\n"
    )
    logs = read_file(evidence["stdout"], checkpoint) + read_file(
        evidence["stderr"], checkpoint
    )
    if evidence["returncode"] != 0 or re.search(
        rb"ERROR:|FAILURE IN SERVER|Exception", logs
    ):
        raise Failure("sclang_error", 10, "sclang failed", evidence)
    if record != expected:
        raise Failure(
            "sclang_unconfirmed",
            10,
            "Missing or inconsistent PREPARED record",
            evidence,
        )
    try:
        manifest = json.loads(read_file(directory / "source-plan.json", checkpoint))
        plan = validate_source_plan(
            read_file(directory / "source.osc", checkpoint),
            read_file(final, checkpoint),
            manifest,
            request["target_frames"],
            request["sample_rate"],
            checkpoint,
        )
    except (ValueError, OSError) as exc:
        raise Failure("source_contract", 2, str(exc)) from exc
    plan.update(
        contract="scs-nrt-source/2",
        resources=[],
        uses=manifest["uses"],
        dependency_coverage="trusted-declared",
        dependencies_inferred=False,
    )
    plan["warnings"] = [
        dict(
            code="sclang_warning",
            stage="prepare",
            message=line,
            hint="See preparation logs",
            details=None,
        )
        for line in logs.decode("utf-8", "replace").splitlines()
        if line.startswith("WARNING:") or "realtime scheduling priority" in line
    ]
    write_json(directory / "resources.json", plan)
    return plan


def run_nrt(request, owner, directory, env, binaries, staging, deadline, checkpoint):
    evidence = owner.run(
        [
            binaries["scsynth"],
            "-N",
            directory / "score.osc",
            "_",
            staging,
            request["sample_rate"],
            "WAV",
            "int16",
            "-i",
            "0",
            "-o",
            request["channels"],
            "-z",
            "64",
            "-D",
            "0",
            "-R",
            "0",
            "-V",
            "0",
        ],
        directory,
        "nrt",
        deadline,
        env,
        checkpoint,
    )
    logs = (
        read_file(evidence["stdout"], checkpoint)
        + read_file(evidence["stderr"], checkpoint)
    ).decode("utf-8", "replace")
    if evidence["returncode"] != 0 or re.search(
        r"ERROR|FAILURE IN SERVER|NRT synthesis failed|exception|alloc failed",
        logs,
        re.I,
    ):
        raise Failure("nrt_error", 11, "scsynth NRT failed", evidence)
    for line in logs.splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r"(?:start time |nextOSCPacket )[0-9.eE+\-]+", line):
            continue
        raise Failure("nrt_unconfirmed", 11, "Unknown NRT diagnostic", {"line": line})
    return evidence


# Protocol numbers from pinned SC_OSC_Commands.h, not server implementation.
OPCODES = dict(
    zip(
        [
            0,
            5,
            9,
            11,
            12,
            14,
            15,
            16,
            17,
            18,
            19,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            48,
            50,
            53,
            59,
            60,
            61,
            62,
        ],
        [
            "cmd_none",
            "/d_recv",
            "/s_new",
            "/n_free",
            "/n_run",
            "/n_map",
            "/n_set",
            "/n_setn",
            "/n_fill",
            "/n_before",
            "/n_after",
            "/g_new",
            "/g_head",
            "/g_tail",
            "/g_freeAll",
            "/c_set",
            "/c_setn",
            "/c_fill",
            "/n_mapn",
            "/g_deepFree",
            "/d_free",
            "/s_newargs",
            "/n_mapa",
            "/n_mapan",
            "/n_order",
        ],
    )
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Binary:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, size):
        require(0 <= size <= len(self.data) - self.pos, "Binary bounds exceeded")
        result = self.data[self.pos : self.pos + size]
        self.pos += size
        return result

    def number(self, fmt):
        return struct.unpack(">" + fmt, self.take(struct.calcsize(">" + fmt)))[0]

    def count(self, fmt="i"):
        value = self.number(fmt)
        require(0 <= value <= len(self.data) - self.pos, "Invalid binary count")
        return value

    def pstring(self):
        return self.take(self.number("B")).decode("utf-8")

    def osc_string(self):
        end = self.data.find(b"\0", self.pos)
        require(end >= self.pos, "Unterminated OSC string")
        length = end - self.pos
        raw = self.take((length + 4) // 4 * 4)
        require(not any(raw[length:]), "Nonzero OSC padding")
        return raw[:length].decode("utf-8")

    def done(self):
        require(self.pos == len(self.data), "Trailing binary data")


def synthdefs(blob, checkpoint=lambda: None):
    reader = Binary(blob)
    require(reader.take(4) == b"SCgf", "Not a SynthDef blob")
    version = reader.number("i")
    require(version in (1, 2), "Unsupported SCgf version")
    width = "i" if version == 2 else "h"
    definitions = {}
    for _ in range(reader.count("h")):
        checkpoint()
        name = reader.pstring()
        require(name and name not in definitions, "Duplicate/empty SynthDef name")
        constants = reader.count(width)
        reader.take(constants * 4)
        parameters = reader.count(width)
        reader.take(parameters * 4)
        for _ in range(reader.count(width)):
            reader.pstring()
            require(
                0 <= reader.number(width) < parameters, "Control index out of bounds"
            )
        outputs = []
        for _ in range(reader.count(width)):
            checkpoint()
            require(bool(reader.pstring()), "Empty UGen name")
            require(reader.number("B") <= 3, "Invalid UGen rate")
            inputs, nout = reader.count(width), reader.count(width)
            reader.number("h")
            for _ in range(inputs):
                source, index = reader.number(width), reader.number(width)
                require(
                    (source == -1 and 0 <= index < constants)
                    or (0 <= source < len(outputs) and 0 <= index < outputs[source]),
                    "Invalid UGen input reference",
                )
            for rate in reader.take(nout):
                require(rate <= 3, "Invalid output rate")
            outputs.append(nout)
        variants = {name}
        for _ in range(reader.count("h")):
            variant = reader.pstring()
            require(variant not in variants, "Duplicate variant")
            variants.add(variant)
            reader.take(parameters * 4)
        definitions[name] = variants
    reader.done()
    return definitions


def osc_message(raw):
    reader = Binary(raw)
    if raw[:1] == b"/":
        command = reader.osc_string()
    else:
        command = OPCODES.get(reader.number("i"))
    require(command in OPCODES.values(), "Unsupported native command: " + str(command))
    tags = reader.osc_string()
    require(tags.startswith(","), "Missing OSC types")
    values, stack = [], []
    current = values
    for tag in tags[1:]:
        if tag == "[":
            array = []
            current.append(array)
            stack.append(current)
            current = array
        elif tag == "]":
            require(bool(stack), "Unbalanced OSC array")
            current = stack.pop()
        elif tag in "ifd":
            value = reader.number({"i": "i", "f": "f", "d": "d"}[tag])
            require(math.isfinite(value), "Nonfinite command argument")
            current.append(value)
        elif tag == "s":
            current.append(reader.osc_string())
        elif tag == "b":
            length = reader.count()
            current.append(reader.take(length))
            # SC 3.14.1 leaves these alignment bytes unspecified; never payload.
            reader.take(-length % 4)
        else:
            raise ValueError("Unsupported OSC type: " + tag)
    require(not stack, "Unclosed OSC array")
    reader.done()
    return command, values


class Arguments:
    def __init__(self, args):
        self.args, self.pos = args, 0

    def get(self, predicate):
        require(self.pos < len(self.args), "Missing command argument")
        value = self.args[self.pos]
        self.pos += 1
        require(predicate(value), "Invalid native command argument")
        return value

    def integer(self):
        return self.get(lambda x: type(x) is int)

    def node(self):
        if self.pos < len(self.args) and isinstance(self.args[self.pos], str):
            self.get(lambda x: re.fullmatch("[htupn]+", x) is not None)
        return self.integer()

    def control(self):
        return self.get(lambda x: isinstance(x, str) or (type(x) is int and x >= 0))

    def value(self, arrays=False):
        def valid(x):
            if type(x) in (int, float):
                return True
            if isinstance(x, str):
                return re.fullmatch("[ac][0-9]+", x) is not None
            return arrays and isinstance(x, list) and all(valid(y) for y in x)

        return self.get(valid)

    def rest(self):
        return self.pos < len(self.args)

    def counted(self, controls):
        while self.rest():
            self.control() if controls else self.integer()
            count = self.integer()
            require(
                0 <= count <= len(self.args) - self.pos, "Invalid command value count"
            )
            for _ in range(count):
                self.value()


def validate_command(command, args, definitions, checkpoint):
    a = Arguments(args)
    if command == "cmd_none":
        require(not args, "cmd_none has trailing arguments")
    elif command == "/d_recv":
        blob = a.get(lambda x: isinstance(x, bytes))
        if a.rest():
            require(a.integer() == 0 and not a.rest(), "Completion program forbidden")
        definitions.update(synthdefs(blob, checkpoint))
    elif command == "/d_free":
        require(bool(args), "Empty d_free")
        while a.rest():
            name = a.get(lambda x: isinstance(x, str))
            if name in definitions:
                del definitions[name]
            else:
                for variants in definitions.values():
                    variants.discard(name)
    elif command in ("/s_new", "/s_newargs"):
        name = a.get(lambda x: isinstance(x, str))
        require(
            any(name in variants for variants in definitions.values()),
            "Missing SynthDef: " + name,
        )
        a.integer()
        require(a.integer() in range(5), "Invalid add action")
        a.node()
        if command == "/s_newargs":
            a.counted(True)
        else:
            while a.rest():
                a.control()
                a.value(arrays=True)
    elif command in ("/n_free", "/g_freeAll", "/g_deepFree"):
        require(bool(args), "Empty node list")
        while a.rest():
            a.node()
    elif command in ("/n_before", "/n_after", "/g_head", "/g_tail", "/n_run", "/g_new"):
        require(bool(args), "Empty node command")
        while a.rest():
            if command == "/g_new":
                a.integer()
                require(a.integer() in range(5), "Invalid add action")
                a.node()
            else:
                a.node()
                a.integer() if command == "/n_run" else a.node()
    elif command == "/n_order":
        require(a.integer() in range(4), "Invalid order action")
        a.node()
        require(a.rest(), "Missing ordered nodes")
        while a.rest():
            a.node()
    elif command in (
        "/n_set",
        "/n_setn",
        "/n_fill",
        "/n_map",
        "/n_mapa",
        "/n_mapn",
        "/n_mapan",
    ):
        a.node()
        if command == "/n_setn":
            a.counted(True)
        else:
            while a.rest():
                a.control()
                if command == "/n_set":
                    a.value(arrays=True)
                elif command == "/n_fill":
                    require(a.integer() >= 0, "Negative fill count")
                    a.value()
                else:
                    require(a.integer() >= -1, "Invalid bus index")
                    if command in ("/n_mapn", "/n_mapan"):
                        require(a.integer() >= 0, "Negative mapping count")
    elif command == "/c_setn":
        a.counted(False)
    elif command in ("/c_set", "/c_fill"):
        while a.rest():
            require(a.integer() >= 0, "Negative bus index")
            if command == "/c_fill":
                require(a.integer() >= 0, "Negative bus count")
            a.get(lambda x: type(x) in (int, float))
    require(not a.rest(), "Trailing command arguments")


def parse_score(data, checkpoint=lambda: None):
    reader = Binary(data)
    bundles, previous = [], 0
    while reader.pos < len(data):
        checkpoint()
        raw = reader.take(reader.count())
        b = Binary(raw)
        require(b.take(8) == b"#bundle\0", "Expected top-level OSC bundle")
        ticks = b.number("Q")
        require(ticks >= previous, "Nonmonotonic Score")
        previous = ticks
        messages = []
        while b.pos < len(raw):
            msg = b.take(b.count())
            command, args = osc_message(msg)
            messages.append((command, args, hashlib.sha256(msg).hexdigest()))
        require(bool(messages), "Empty OSC bundle")
        bundles.append((ticks, messages))
    require(bool(bundles), "Empty Score")
    return bundles


def validate_source_plan(
    source, final, manifest, frames, rate, checkpoint=lambda: None
):
    try:
        require(
            isinstance(manifest, dict)
            and manifest.get("contract") == "scs-nrt-source/2",
            "Wrong source contract",
        )
        require(
            manifest.get("resources") == [],
            "Nonempty Buffer declarations unsupported in this slice",
        )
        uses = manifest.get("uses")
        require(isinstance(uses, list), "Explicit uses array required")
        bundles = parse_score(source, checkpoint)
        instrumented = parse_score(final, checkpoint)
        require(
            len(instrumented) == len(bundles) + 1 and instrumented[:-1] == bundles,
            "Source/final Score correspondence failed",
        )
        terminal, terminal_messages = instrumented[-1]
        require(
            len(terminal_messages) == 1
            and terminal_messages[0][:2] == ("cmd_none", []),
            "Missing terminal no-op",
        )
        require(
            abs(terminal * rate - frames * (1 << 32)) <= rate,
            "Terminal timestamp mismatch",
        )
        definitions, anchors = {}, {}
        for bi, (ticks, messages) in enumerate(bundles):
            require(ticks <= terminal, "Event beyond duration")
            for mi, (command, args, digest) in enumerate(messages):
                validate_command(command, args, definitions, checkpoint)
                if command in ("/s_new", "/s_newargs"):
                    anchors[(bi, mi)] = dict(ticks=ticks, sha256=digest)
        coverage = set()
        for use in uses:
            require(
                isinstance(use, dict)
                and set(use) == {"anchor", "from", "through", "resources"},
                "Malformed use declaration",
            )
            anchor = use["anchor"]
            require(
                isinstance(anchor, list)
                and len(anchor) == 2
                and all(type(x) is int and x >= 0 for x in anchor),
                "Malformed anchor",
            )
            key = tuple(anchor)
            require(
                key in anchors and use["resources"] == [], "Invalid anchor/resources"
            )
            start, through = use["from"], use["through"]
            require(
                type(start) in (int, float)
                and type(through) in (int, float)
                and math.isfinite(start)
                and math.isfinite(through)
                and 0 <= start <= through <= frames / rate,
                "Invalid usage interval",
            )
            # Coverage belongs to the anchor's collection of intervals, not
            # every interval: later declarations may start after creation.
            if (
                start * (1 << 32) <= anchors[key]["ticks"] + 1
                and through * (1 << 32) + 1 >= anchors[key]["ticks"]
            ):
                coverage.add(key)
        require(coverage == set(anchors), "Missing uses declaration for synth creation")
        return dict(
            terminal_osc_ticks=terminal,
            generations=0,
            verified_generations=0,
            source_score_sha256=hashlib.sha256(source).hexdigest(),
            final_score_sha256=hashlib.sha256(final).hexdigest(),
            anchors=[dict(anchor=list(key), **value) for key, value in anchors.items()],
        )
    except (UnicodeError, KeyError, TypeError, struct.error) as exc:
        raise ValueError("Malformed source plan: " + str(exc)) from exc
