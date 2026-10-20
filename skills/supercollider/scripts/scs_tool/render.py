"""Render coordinator and comparison policy."""

import os
import re
import hashlib
import platform
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

Q = 1 << 32


def compare_audio(request, effective, measured):
    mismatches = {
        key: {"expected": expected, "measured": measured.get(key)}
        for key, expected in [
            ("sample_rate", request["sample_rate"]),
            ("channels", request["channels"]),
            ("frames", effective["expected_frames"]),
        ]
        if measured.get(key) != expected
    }
    if mismatches:
        raise ValueError(str(mismatches))
    return True


class Cancelled(Exception):
    def __init__(self, signum):
        self.signum = signum


def execute(argv, cancelled=lambda: None):
    """One run owns all mutable state; no tracker/harness/global runtime state."""
    from . import files, sc
    from .processes import ProcessOwner, CleanupError
    from .wav import read_wav

    result = dict(
        schema_version=2,
        operation="render",
        run_id=uuid.uuid4().hex,
        status="error",
        stage="input",
        exit_code=20,
        requested=None,
        effective=None,
        measured=None,
        resource_evidence=None,
        artifacts={"ready": [], "partial": []},
        diagnostics={"directory": None, "logs": [], "processes": []},
        environment={
            "tool": "nrt-render/2-alpha",
            "python": platform.python_version(),
            "sclang": None,
            "scsynth": None,
            "platform": sys.platform + "-" + platform.machine(),
        },
        warnings=[],
        errors=[],
        unfinished_actions=[],
    )
    stage = "input"
    directory = work = stage_dir = staging = owner = parent_fd = None
    deadline = time.monotonic() + 120
    published = verified = False
    plan = None

    def checkpoint():
        signum = cancelled()
        if signum:
            raise Cancelled(signum)
        if time.monotonic() >= deadline:
            raise TimeoutError("Overall render deadline exceeded")

    def fail(code, exit_code, message, details=None, failure_stage=None):
        result["artifacts"]["partial"].extend(
            {**a, "reason": "published_not_ready"} for a in result["artifacts"]["ready"]
        )
        result["artifacts"]["ready"] = []
        result["errors"].append(
            dict(
                code=code,
                stage=failure_stage or stage,
                message=message,
                hint="Inspect retained logs and the render/source contract",
                details=details,
            )
        )
        result["exit_code"] = exit_code
        result["stage"] = failure_stage or stage
        result["status"] = (
            "timeout"
            if exit_code == 24
            else "cancelled"
            if exit_code in (130, 143)
            else "error"
        )

    def observe_final_cancellation():
        # Do not interrupt mandatory cleanup or override a prior cleanup failure.
        signum = cancelled()
        if signum and result["status"] == "success":
            fail(
                "cancelled",
                128 + signum,
                "Cancelled during finalization",
                failure_stage="cleanup",
            )
            return True
        return False

    started = time.monotonic()
    try:
        try:
            request = validate_request(argv)
        except (ValueError, OSError) as exc:
            raise sc.Failure("invalid_input", 2, str(exc)) from exc
        result["requested"] = {
            key: request[key]
            for key in [
                "source",
                "output",
                "duration_seconds",
                "sample_rate",
                "channels",
                "format",
                "sample_format",
                "seed",
                "timeout_seconds",
            ]
        }
        deadline = started + request["timeout_seconds"]
        checkpoint()
        output = Path(request["output"])
        if os.path.lexists(output):
            raise sc.Failure("output_exists", 14, "Existing output is protected")
        parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        if output.resolve() == Path(request["source"]).resolve():
            raise sc.Failure("invalid_input", 2, "Output aliases source")
        directory = files.private_directory(
            request.get("diagnostics_dir") or request.get("temp_dir"),
            "scs-diagnostics-",
        )
        result["diagnostics"]["directory"] = str(directory)
        work = files.private_directory(request.get("temp_dir"), "scs-work-")
        stage_dir = files.private_directory(output.parent, ".scs-staging-")
        staging = stage_dir / "output.wav"
        env = files.child_environment(work)
        owner = ProcessOwner()
        stage = "dependencies"
        if (
            sys.platform != "linux"
            or platform.machine() != "x86_64"
            or platform.python_version() != "3.14.7"
        ):
            raise sc.Failure(
                "unsupported_environment",
                3,
                "Supported profile: Linux x86_64 CPython 3.14.7",
            )
        binaries, versions = sc.discover(
            request, owner, directory, env, deadline, checkpoint
        )
        result["environment"].update(versions)
        if versions["local_help"] is None:
            result["warnings"].append(
                dict(
                    code="local_help_missing",
                    stage=stage,
                    message="Matching local HelpSource unavailable",
                    hint="Provide matching local documentation",
                    details=None,
                )
            )
        stage = "prepare"
        source_hash = hashlib.sha256(
            sc.read_file(request["source"], checkpoint)
        ).hexdigest()
        plan = sc.prepare_score(
            request,
            owner,
            directory,
            env,
            binaries,
            deadline,
            result["run_id"],
            checkpoint,
        )
        result["warnings"].extend(plan.get("warnings", []))
        if (
            hashlib.sha256(sc.read_file(request["source"], checkpoint)).hexdigest()
            != source_hash
        ):
            raise sc.Failure("source_contract", 2, "Source changed during preparation")
        effective = timing(
            request["target_frames"], request["sample_rate"], plan["terminal_osc_ticks"]
        )
        effective["source_contract"] = "scs-nrt-source/2"
        result["effective"] = effective
        result["resource_evidence"] = dict(
            dependency_coverage="trusted-declared",
            dependencies_inferred=False,
            generations=plan["generations"],
            verified_generations=0,
            manifest=str(directory / "resources.json"),
        )
        plan["source_sha256"] = source_hash
        files.write_json(directory / "resources.json", plan)
        checkpoint()
        stage = "nrt"
        sc.run_nrt(
            request, owner, directory, env, binaries, staging, deadline, checkpoint
        )
        stage = "resources"
        checkpoint()
        try:
            sc.verify_resources(plan, checkpoint)
        finally:
            result["resource_evidence"]["verified_generations"] = plan[
                "verified_generations"
            ]
            files.write_json(directory / "resources.json", plan)
        stage = "audio"
        try:
            measured = read_wav(staging, checkpoint)
        except ValueError as exc:
            raise sc.Failure("audio_invalid", 12, str(exc)) from exc
        result["measured"] = measured
        try:
            compare_audio(request, effective, measured)
        except ValueError as exc:
            raise sc.Failure(
                "audio_mismatch",
                13,
                str(exc),
                {
                    "requested": result["requested"],
                    "effective": effective,
                    "measured": measured,
                },
            ) from exc
        verified = True
        stage = "publish"
        checkpoint()
        files.publish_no_replace(staging, output, parent_fd)
        published = True
        checkpoint()
        result.update(status="success", stage="complete", exit_code=0)
    except sc.Failure as exc:
        fail(exc.code, exc.exit_code, str(exc), exc.details)
    except Cancelled as exc:
        fail(
            "cancelled", 128 + exc.signum, "Cancelled by signal", {"signal": exc.signum}
        )
    except TimeoutError as exc:
        fail("timeout", 24, str(exc))
    except CleanupError as exc:
        cause = exc.__cause__ or exc.__context__
        if isinstance(cause, TimeoutError):
            fail("timeout", 24, str(cause))
        elif isinstance(cause, Cancelled):
            fail("cancelled", 128 + cause.signum, str(cause))
        elif isinstance(cause, sc.Failure):
            fail(cause.code, cause.exit_code, str(cause), cause.details)
        elif isinstance(cause, OverflowError):
            fail("resource_limit", 21, str(cause))
        elif cause is not None:
            fail("wrapper_error", 20, type(cause).__name__ + ": " + str(cause))
        fail("cleanup_failed", 25, str(exc), failure_stage="cleanup")
        result["unfinished_actions"].append(
            {"action": "reap_owned_processes", "details": str(exc)}
        )
    except OverflowError as exc:
        fail("resource_limit", 21, str(exc))
    except FileExistsError as exc:
        fail("output_exists", 14, str(exc))
    except OSError as exc:
        fail("file_error", 14, str(exc))
    except Exception as exc:
        fail("wrapper_error", 20, type(exc).__name__ + ": " + str(exc))
    finally:
        if owner is not None:
            try:
                owner.cleanup()
            except Exception as exc:
                fail("cleanup_failed", 25, str(exc), failure_stage="cleanup")
                result["unfinished_actions"].append(
                    {"action": "reap_owned_processes", "details": str(exc)}
                )
            result["diagnostics"]["processes"] = owner.evidence
            result["diagnostics"]["logs"] = [
                rec[key] for rec in owner.evidence for key in ["stdout", "stderr"]
            ]
        keep_partial = bool(staging is not None and staging.exists() and not published)
        unfinished = files.finalize_run(work, stage_dir, keep_partial)
        if unfinished:
            result["unfinished_actions"].extend(unfinished)
            fail(
                "cleanup_failed",
                25,
                "Owned file cleanup incomplete",
                unfinished,
                failure_stage="cleanup",
            )
        if parent_fd is not None:
            os.close(parent_fd)
        observe_final_cancellation()
        if published:
            artifact = dict(
                path=request["output"],
                kind="audio",
                format="wav",
                verified=verified,
                published=True,
            )
            if result["status"] == "success":
                result["artifacts"]["ready"].append(artifact)
            else:
                result["artifacts"]["partial"].append(
                    {**artifact, "reason": "published_not_ready"}
                )
        elif keep_partial:
            result["artifacts"]["partial"].append(
                dict(
                    path=str(staging),
                    kind="audio",
                    verified=verified,
                    published=False,
                    reason="render_not_complete",
                )
            )
        if directory is not None:
            try:
                if plan is not None:
                    for g in plan["resources"]:
                        for role in ("canonical", "reference", "snapshot"):
                            path = Path(g["prepared"][role])
                            if result["status"] == "success":
                                try:
                                    path.unlink(missing_ok=True)
                                    g["retention"][role] = "removed"
                                except OSError as exc:
                                    g["retention"][role] = "cleanup_failed"
                                    action = dict(
                                        action="remove_owned_file", path=str(path)
                                    )
                                    result["unfinished_actions"].append(action)
                                    fail(
                                        "cleanup_failed",
                                        25,
                                        str(exc),
                                        action,
                                        "cleanup",
                                    )
                            else:
                                g["retention"][role] = (
                                    "retained" if path.exists() else "absent"
                                )
                        if "input" in g:
                            path = Path(g["input"]["staged"])
                            if result["status"] == "success":
                                try:
                                    path.unlink(missing_ok=True)
                                    g["input"]["retention"] = "removed"
                                except OSError as exc:
                                    g["input"]["retention"] = "cleanup_failed"
                                    action = dict(
                                        action="remove_owned_file", path=str(path)
                                    )
                                    result["unfinished_actions"].append(action)
                                    fail(
                                        "cleanup_failed",
                                        25,
                                        str(exc),
                                        action,
                                        "cleanup",
                                    )
                            else:
                                g["input"]["retention"] = (
                                    "retained" if path.exists() else "absent"
                                )
                    files.write_json(directory / "resources.json", plan)
                files.write_json(
                    directory / "files.json",
                    dict(
                        diagnostics={"path": str(directory), "retention": "retained"},
                        work={
                            "path": str(work),
                            "retention": "cleanup_failed"
                            if work and work.exists()
                            else "removed",
                        },
                        staging={
                            "path": str(stage_dir),
                            "retention": "partial" if keep_partial else "removed",
                        },
                        source={
                            "path": result["requested"]["source"],
                            "role": "read_only_input",
                        },
                        files=[str(p) for p in directory.iterdir()],
                    ),
                )
                observe_final_cancellation()
                files.write_json(directory / "result.json", result)
                # A signal may also arrive while the result itself is saved.
                if observe_final_cancellation():
                    files.write_json(directory / "result.json", result)
            except Exception as exc:
                result["artifacts"]["partial"].extend(
                    {**a, "reason": "published_not_ready"}
                    for a in result["artifacts"]["ready"]
                )
                result["artifacts"]["ready"] = []
                fail(
                    "cleanup_failed",
                    25,
                    "Cannot retain final evidence: " + str(exc),
                    failure_stage="cleanup",
                )
                result["unfinished_actions"].append(
                    {"action": "save_evidence", "path": str(directory)}
                )
    return result


def timing(frames, rate, terminal=None):
    terminal = frames * Q // rate if terminal is None else terminal
    increment = 64 * Q // rate
    expected = 64 * max(1, (terminal + increment - 1) // increment)
    return dict(
        target_frames=frames,
        terminal_osc_ticks=terminal,
        osc_increment_ticks=increment,
        block_size=64,
        nominal_duration_seconds=frames / rate,
        expected_frames=expected,
        expected_padding_frames=expected - frames,
        expected_duration_seconds=expected / rate,
        duration_tolerance_frames=0,
    )


def validate_request(argv, cwd=None):
    """Normalize an explicit request; paths are data relative to initial cwd."""
    required = {"source", "output", "duration", "sample-rate", "channels"}
    allowed = required | {
        "format",
        "seed",
        "timeout",
        "sclang",
        "scsynth",
        "sc-class-library",
        "temp-dir",
        "diagnostics-dir",
        "json",
    }
    values = {}
    if not argv or argv[0] != "render":
        raise ValueError("Only render is supported")
    i = 1
    while i < len(argv):
        key, sep, value = argv[i].partition("=")
        if not key.startswith("--") or key[2:] not in allowed or key in values:
            raise ValueError("Unknown or repeated parameter: " + key)
        if key == "--json":
            if sep:
                raise ValueError("--json takes no value")
            value = True
        elif not sep:
            i += 1
            if i == len(argv) or argv[i].startswith("--"):
                raise ValueError("Missing value for " + key)
            value = argv[i]
        values[key] = value
        i += 1
    if any("--" + key not in values for key in required):
        raise ValueError("source/output/duration/sample-rate/channels are required")
    for key, low, high, default in [
        ("sample-rate", 8000, 192000, None),
        ("channels", 1, 32, None),
        ("seed", 0, 2147483647, "0"),
        ("timeout", 1, 86400, "120"),
    ]:
        value = values.get("--" + key, default)
        if not re.fullmatch(r"[0-9]+", value or "") or not low <= int(value) <= high:
            raise ValueError("Invalid " + key)
        values["--" + key] = value
    if values.get("--format", "wav") != "wav":
        raise ValueError("Only WAV PCM16 is supported")
    rate = int(values["--sample-rate"])
    try:
        duration = Decimal(values["--duration"])
        if not duration.is_finite() or not 0 < duration <= 86400:
            raise ValueError("Invalid duration")
        with localcontext() as ctx:
            ctx.prec = max(40, len(values["--duration"]) + 10)
            frames = int((duration * rate).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError("Invalid duration") from exc
    channels = int(values["--channels"])
    model = timing(frames, rate)
    if frames < 1 or 2 * channels * model["expected_frames"] + 4096 > Q - 1:
        raise ValueError("Frame count outside supported RIFF limits")
    root = Path(cwd or Path.cwd())
    source = (root / values["--source"]).resolve()
    if not source.is_file() or not os.access(source, os.R_OK):
        raise ValueError("Source must be a readable file")
    extras = {}
    for key in ["sclang", "scsynth", "sc-class-library", "temp-dir", "diagnostics-dir"]:
        if "--" + key in values:
            path = (root / values["--" + key]).absolute()
            if key.endswith("dir") or key == "sc-class-library":
                if not path.is_dir():
                    raise ValueError(key + " must be an existing directory")
            extras[key.replace("-", "_")] = str(path)
    return dict(
        source=str(source),
        output=str((root / values["--output"]).absolute()),
        duration_seconds=values["--duration"],
        sample_rate=rate,
        channels=channels,
        format="wav",
        sample_format="int16",
        seed=int(values["--seed"]),
        timeout_seconds=int(values["--timeout"]),
        **model,
        **extras,
    )
