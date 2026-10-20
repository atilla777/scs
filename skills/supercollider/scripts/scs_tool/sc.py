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
    try:
        read_canonical_resource(plan, manifest, directory, checkpoint)
    except (ValueError, OSError) as exc:
        plan.update(run_id=token, preparation_error=str(exc))
        write_json(directory / "resources.json", plan)
        raise Failure("source_contract", 2, str(exc)) from exc
    plan.update(
        run_id=token,
        contract="scs-nrt-source/2",
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


def file_hash(path, checkpoint=lambda: None):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while raw := stream.read(65536):
            checkpoint()
            digest.update(raw)
    return digest.hexdigest()


def read_canonical_resource(plan, manifest, directory, checkpoint=lambda: None):
    from .wav import FloatInput, compare_resource_state

    for index, g in enumerate(plan["resources"]):
        p = g["prepared"]
        base = directory / ("resource-" + str(index))
        for key, suffix in (
            ("canonical", ".canonical.wav"),
            ("reference", ".reference.f32"),
            ("snapshot", ".snapshot.wav"),
        ):
            require(p[key] == str(base) + suffix, "Foreign/stale evidence path")
        require(not os.path.lexists(p["snapshot"]), "Snapshot exists before NRT")
        g["canonical_comparison"] = compare_resource_state(
            p["reference"], p["canonical"], p, checkpoint
        )
        initial = g["initial"]
        if initial["kind"] in ("zero", "data"):
            reader = FloatInput(p["reference"], p)
            try:
                position = 0
                for block in reader.blocks(checkpoint):
                    for value in block:
                        expected = (
                            0.0
                            if initial["kind"] == "zero"
                            else struct.unpack(
                                "<f", struct.pack("<f", initial["samples"][position])
                            )[0]
                        )
                        require(
                            value == expected,
                            "Reference differs from declared initial state",
                        )
                        position += 1
            finally:
                reader.close()
        g["retention"] = {
            key: "pending" for key in ("canonical", "reference", "snapshot")
        }
    staged = manifest.get("staged_inputs", [])
    require(isinstance(staged, list), "Malformed staged input map")
    file_generations = [
        (i, g)
        for i, g in enumerate(plan["resources"])
        if g["initial"]["kind"] == "file"
    ]
    require(len(staged) == len(file_generations), "Missing staged input identity")
    for item, (index, g) in zip(staged, file_generations):
        require(
            isinstance(item, dict)
            and set(item) == {"original", "staged", "size", "mtime"},
            "Malformed input identity",
        )
        original, copy = Path(item["original"]), Path(item["staged"])
        require(
            str(original) == g["initial"]["path"]
            and copy == directory / ("resource-" + str(index) + ".input"),
            "Foreign staged input",
        )
        before = original.stat()
        require(
            original.is_file()
            and not copy.is_symlink()
            and copy.is_file()
            and before.st_size == item["size"] == copy.stat().st_size
            and int(before.st_mtime) == item["mtime"],
            "Input changed/short copy",
        )
        original_hash, copy_hash = (
            file_hash(original, checkpoint),
            file_hash(copy, checkpoint),
        )
        after = original.stat()
        identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(
            all(getattr(after, key) == getattr(before, key) for key in identity_fields)
            and original_hash == copy_hash,
            "Input changed during staging",
        )
        g["input"] = dict(item, sha256=copy_hash, retention="pending")


def verify_resources(plan, checkpoint=lambda: None):
    from .wav import compare_resource_state, read_buffer_snapshot

    for g in plan["resources"]:
        p = g["prepared"]
        g["comparison"] = dict(
            matches=False,
            measured=None,
            reason="snapshot_missing",
            expected={k: p[k] for k in ("frames", "channels", "sample_rate")},
        )
        try:
            if not os.path.lexists(p["snapshot"]):
                raise Failure(
                    "resource_evidence_missing",
                    11,
                    "Missing generation snapshot",
                    {"id": g["id"]},
                )
            measured = compare_resource_state(
                p["reference"], p["snapshot"], p, checkpoint
            )
        except ValueError as exc:
            g["comparison"]["reason"] = str(exc)
            try:
                g["comparison"]["measured"] = read_buffer_snapshot(
                    p["snapshot"], checkpoint
                )
            except ValueError:
                pass
            code = (
                "resource_evidence_mismatch"
                if "mismatch" in str(exc)
                else "resource_evidence_invalid"
            )
            raise Failure(
                code, 11, str(exc), {"id": g["id"], "snapshot": p["snapshot"]}
            ) from exc
        g["comparison"] = measured
        plan["verified_generations"] += 1


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


def osc_message(raw, generated=False):
    reader = Binary(raw)
    if raw[:1] == b"/":
        command = reader.osc_string()
    else:
        opcode = reader.number("i")
        command = OPCODES.get(opcode)
        if generated and command is None:
            command = {
                28: "/b_alloc",
                29: "/b_allocRead",
                32: "/b_free",
                31: "/b_write",
            }.get(opcode)
    allowed = set(OPCODES.values())
    if generated:
        allowed.update(("/b_alloc", "/b_allocRead", "/b_free", "/b_write"))
    require(command in allowed, "Unsupported native command: " + str(command))
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


def parse_score(data, checkpoint=lambda: None, generated=False):
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
            command, args = osc_message(msg, generated)
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
        resources = validate_generations(manifest.get("resources"), frames, rate)
        uses = manifest.get("uses")
        require(isinstance(uses, list), "Explicit uses array required")
        bundles = parse_score(source, checkpoint)
        instrumented = parse_score(final, checkpoint, generated=True)
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
                key in anchors
                and isinstance(use["resources"], list)
                and len(set(use["resources"])) == len(use["resources"])
                and all(identifier in resources for identifier in use["resources"]),
                "Invalid anchor/resources",
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
            for identifier in use["resources"]:
                g = resources[identifier]
                require(start >= g["at"], "Consumer precedes initialization")
                require(
                    block_at(start, rate) >= g["ready_block"], "Use before readiness"
                )
                require(
                    g["retire_block"] is None
                    or block_at(through, rate) < g["retire_block"],
                    "Use outside generation lifetime",
                )
            # Coverage belongs to the anchor's collection of intervals, not
            # every interval: later declarations may start after creation.
            if (
                start * (1 << 32) <= anchors[key]["ticks"] + 1
                and through * (1 << 32) + 1 >= anchors[key]["ticks"]
            ):
                coverage.add(key)
        require(coverage == set(anchors), "Missing uses declaration for synth creation")
        validate_instrumentation(bundles, instrumented, resources, terminal)
        return dict(
            terminal_osc_ticks=terminal,
            generations=len(resources),
            verified_generations=0,
            resources=list(resources.values()),
            source_score_sha256=hashlib.sha256(source).hexdigest(),
            final_score_sha256=hashlib.sha256(final).hexdigest(),
            anchors=[dict(anchor=list(key), **value) for key, value in anchors.items()],
        )
    except (UnicodeError, KeyError, TypeError, struct.error) as exc:
        raise ValueError("Malformed source plan: " + str(exc)) from exc


def block_at(seconds, rate):
    return max(
        1,
        (int(seconds * (1 << 32)) + (64 * (1 << 32) // rate) - 1)
        // (64 * (1 << 32) // rate),
    )


def validate_generations(declarations, frames, rate):
    require(isinstance(declarations, list), "Explicit resources array required")
    result, paths = {}, set()
    for declaration in declarations:
        require(
            isinstance(declaration, dict)
            and set(declaration)
            == {"id", "bufnum", "at", "retire", "initial", "prepared"},
            "Malformed generation declaration",
        )
        g = dict(declaration)
        identifier = g["id"]
        require(
            isinstance(identifier, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier)
            and identifier not in result,
            "Invalid/duplicate generation ID",
        )
        require(type(g["bufnum"]) is int and 0 <= g["bufnum"] <= 1023, "Invalid bufnum")
        for key in ("at", "retire"):
            t = g[key]
            require(
                (t is None and key == "retire")
                or (
                    type(t) in (int, float)
                    and math.isfinite(t)
                    and 0 <= t <= frames / rate
                ),
                "Invalid generation time",
            )
        require(g["retire"] is None or g["retire"] > g["at"], "Invalid retirement")
        initial, p = g["initial"], g["prepared"]
        require(
            isinstance(initial, dict)
            and initial.get("kind") in ("file", "data", "zero"),
            "Unsupported resource mode",
        )
        require(
            isinstance(p, dict)
            and set(p)
            == {
                "frames",
                "channels",
                "sample_rate",
                "canonical",
                "reference",
                "snapshot",
            },
            "Malformed preparation metadata",
        )
        n, c, r = p["frames"], p["channels"], p["sample_rate"]
        require(
            all(type(v) is int and v > 0 for v in (n, c, r))
            and n * c <= (1 << 31) - 1
            and 4 * c <= 65535
            and r <= (1 << 24)
            and n * c * 4 + 4096 <= (1 << 32) - 1,
            "Unrepresentable resource",
        )
        if initial["kind"] in ("data", "zero"):
            required = {"kind", "frames", "channels", "sample_rate"}
            if initial["kind"] == "data":
                required.add("samples")
            require(
                set(initial) == required
                and all(
                    type(initial[k]) is int and initial[k] == p[k]
                    for k in ("frames", "channels", "sample_rate")
                ),
                "Invalid initial dimensions",
            )
            if initial["kind"] == "data":
                samples = initial["samples"]
                require(
                    isinstance(samples, list) and len(samples) == n * c,
                    "Invalid sample count",
                )
                require(
                    all(
                        type(x) in (int, float)
                        and math.isfinite(x)
                        and abs(x) <= 3.4028234663852886e38
                        for x in samples
                    ),
                    "Nonfinite/unrepresentable initial samples",
                )
        else:
            require(
                set(initial) == {"kind", "path", "start_frame", "frames", "channels"}
                and isinstance(initial["path"], str)
                and initial["path"]
                and type(initial["start_frame"]) is int
                and initial["start_frame"] >= 0
                and (
                    initial["frames"] is None
                    or type(initial["frames"]) is int
                    and initial["frames"] == n
                )
                and (
                    initial["channels"] is None
                    or isinstance(initial["channels"], list)
                    and len(initial["channels"]) == c
                    and all(type(x) is int and x >= 0 for x in initial["channels"])
                ),
                "Malformed file initial state",
            )
        for key in ("canonical", "reference", "snapshot"):
            path = p[key]
            require(
                isinstance(path, str)
                and Path(path).is_absolute()
                and path not in paths,
                "Invalid/duplicate evidence path",
            )
            paths.add(path)
        g["ready_block"] = block_at(g["at"], rate)
        g["retire_block"] = None if g["retire"] is None else block_at(g["retire"], rate)
        require(
            g["retire_block"] is None or g["retire_block"] > g["ready_block"],
            "Empty block lifetime",
        )
        for old in result.values():
            if old["bufnum"] == g["bufnum"]:
                earlier, later = sorted((old, g), key=lambda item: item["at"])
                require(
                    earlier["retire"] is not None
                    and earlier["retire"] <= later["at"]
                    and earlier["retire_block"] is not None
                    and earlier["retire_block"] <= later["ready_block"],
                    "Overlapping Buffer generations",
                )
        result[identifier] = g
    return result


def validate_instrumentation(source, final, resources, terminal):
    """Compare generated commands exactly; user messages retain raw-byte hashes."""
    expected = []
    for index, g in enumerate(resources.values()):
        p, b = g["prepared"], g["bufnum"]
        ticks = int(g["at"] * (1 << 32))
        init = (
            ("/b_alloc", [b, p["frames"], p["channels"], 0, p["sample_rate"]])
            if g["initial"]["kind"] == "zero"
            else ("/b_allocRead", [b, p["canonical"], 0, -1])
        )
        for offset, item in enumerate(
            [
                ("/b_free", [b]),
                init,
                ("/b_write", [b, p["snapshot"], "WAV", "float", -1, 0, 0]),
            ]
        ):
            expected.append((ticks, 1, index * 3 + offset, item))
        if g["retire"] is not None:
            expected.append((int(g["retire"] * (1 << 32)), 0, index, ("/b_free", [b])))
    order = 0
    for ticks, messages in source:
        for command, args, digest in messages:
            expected.append((ticks, 2, order, (command, args, digest)))
            order += 1
    expected.append((terminal, 3, 0, ("cmd_none", [])))
    actual = [(ticks, msg) for ticks, messages in final for msg in messages]
    expected.sort(key=lambda item: item[:3])
    require(len(expected) == len(actual), "Instrumentation message count mismatch")
    for (ticks, _, _, item), (actual_ticks, msg) in zip(expected, actual):
        require(
            abs(ticks - actual_ticks) <= (0 if len(item) == 3 else 1)
            and (item == msg if len(item) == 3 else item == msg[:2]),
            "Source/final Score instrumentation correspondence failed",
        )
