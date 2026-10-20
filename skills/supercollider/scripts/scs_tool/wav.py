"""Full bounded PCM16 measurement, independent of acceptance policy."""

import hashlib
import math
import os
import stat
import struct
import wave


def read_wav(path, checkpoint=lambda: None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("WAV must be regular")
            head = stream.read(12)
            if len(head) != 12 or head[:4] != b"RIFF" or head[8:] != b"WAVE":
                raise ValueError("Not RIFF/WAVE")
            if struct.unpack("<I", head[4:8])[0] + 8 != size:
                raise ValueError("RIFF size mismatch")
            fmt = data_size = None
            while stream.tell() < size:
                checkpoint()
                chunk = stream.read(8)
                if len(chunk) != 8:
                    raise ValueError("Short chunk header")
                name, length = struct.unpack("<4sI", chunk)
                end = stream.tell() + length
                if end + (length & 1) > size:
                    raise ValueError("Truncated chunk")
                if name == b"fmt ":
                    if fmt is not None or length < 16 or length > 65536:
                        raise ValueError("Invalid fmt chunk")
                    raw = stream.read(length)
                    fmt = struct.unpack("<HHIIHH", raw[:16])
                    kind, channels, rate, byte_rate, align, bits = fmt
                    if kind == 65534:
                        if (
                            length < 40
                            or struct.unpack("<H", raw[16:18])[0] < 22
                            or struct.unpack("<H", raw[18:20])[0] != 16
                            or raw[24:40]
                            != bytes.fromhex("0100000000001000800000aa00389b71")
                        ):
                            raise ValueError("Unsupported extensible subtype")
                    elif kind != 1:
                        raise ValueError("Not PCM")
                    if (
                        channels < 1
                        or rate < 1
                        or bits != 16
                        or align != channels * 2
                        or byte_rate != rate * align
                    ):
                        raise ValueError("Invalid PCM16 properties")
                elif name == b"data":
                    if data_size is not None or fmt is None:
                        raise ValueError("Duplicate or unordered data")
                    data_size = length
                stream.seek(end + (length & 1))
            if fmt is None or data_size is None or data_size % fmt[4]:
                raise ValueError("Missing or incomplete PCM data")
            stream.seek(0)
            digest = hashlib.sha256()
            while block := stream.read(65536):
                checkpoint()
                digest.update(block)
            stream.seek(0)
            decoded = 0
            with wave.open(stream, "rb") as audio:
                while block := audio.readframes(8192):
                    checkpoint()
                    if len(block) % fmt[4]:
                        raise ValueError("Short audio read")
                    for _ in struct.iter_unpack("<h", block):
                        decoded += 1
                frames = decoded // fmt[1]
                if frames != audio.getnframes() or frames * fmt[4] != data_size:
                    raise ValueError("Decoded frame count mismatch")
            return dict(
                frames=frames,
                sample_rate=fmt[2],
                channels=fmt[1],
                duration_seconds=frames / fmt[2],
                format="wav",
                sample_format="int16",
                decoded_samples=decoded,
                sha256=digest.hexdigest(),
            )
    except TimeoutError:
        raise
    except (OSError, EOFError, wave.Error, struct.error) as exc:
        raise ValueError("Invalid or unavailable WAV: " + str(exc)) from exc


class FloatInput:
    """Owned regular float32 file; bounded decoding and normalized sample hash."""

    def __init__(self, path, expected=None):
        self.stream = None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            self.stream = os.fdopen(fd, "rb")
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Resource must be regular")
            self.size = info.st_size
            self.file_hash = hashlib.sha256()
            self.sample_hash = hashlib.sha256()
            self.decoded = 0
            if expected is not None:
                self.properties = {
                    k: expected[k] for k in ("frames", "channels", "sample_rate")
                }
                self.offset, self.length = 0, self.size
                if self.size != expected["frames"] * expected["channels"] * 4:
                    raise ValueError("Short/extra reference payload")
            else:
                self._riff()
        except Exception:
            self.close()
            raise

    def _riff(self):
        s = self.stream
        header = s.read(12)
        if (
            len(header) != 12
            or header[:4] != b"RIFF"
            or header[8:] != b"WAVE"
            or struct.unpack("<I", header[4:8])[0] + 8 != self.size
        ):
            raise ValueError("Invalid resource RIFF bounds")
        fmt = data = None
        while s.tell() < self.size:
            chunk = s.read(8)
            if len(chunk) != 8:
                raise ValueError("Truncated resource chunk")
            name, length = struct.unpack("<4sI", chunk)
            end = s.tell() + length
            if end + (length & 1) > self.size:
                raise ValueError("Truncated resource data")
            if name == b"fmt ":
                if fmt is not None or not 16 <= length <= 65536:
                    raise ValueError("Invalid float fmt")
                raw = s.read(length)
                fmt = struct.unpack("<HHIIHH", raw[:16])
                kind, channels, rate, byte_rate, align, bits = fmt
                if kind == 65534:
                    if (
                        length < 40
                        or struct.unpack_from("<H", raw, 16)[0] < 22
                        or struct.unpack_from("<H", raw, 18)[0] != 32
                        or raw[24:40]
                        != bytes.fromhex("0300000000001000800000aa00389b71")
                    ):
                        raise ValueError("Unsupported float subtype")
                elif kind != 3:
                    raise ValueError("Resource is not IEEE float")
                if (
                    channels < 1
                    or rate < 1
                    or bits != 32
                    or align != channels * 4
                    or byte_rate != rate * align
                ):
                    raise ValueError("Invalid float32 properties")
            elif name == b"data":
                if fmt is None or data is not None:
                    raise ValueError("Duplicate/unordered resource data")
                data = (s.tell(), length)
            s.seek(end + (length & 1))
        if fmt is None or data is None or data[1] % fmt[4]:
            raise ValueError("Incomplete float32 resource")
        self.offset, self.length = data
        self.properties = dict(
            frames=self.length // fmt[4], channels=fmt[1], sample_rate=fmt[2]
        )

    def blocks(self, checkpoint):
        s = self.stream
        s.seek(0)
        while raw := s.read(65536):
            checkpoint()
            self.file_hash.update(raw)
        s.seek(self.offset)
        remaining = self.length
        while remaining:
            checkpoint()
            raw = s.read(min(65536, remaining))
            if not raw or len(raw) % 4:
                raise ValueError("Short float32 read")
            remaining -= len(raw)
            values = tuple(x[0] for x in struct.iter_unpack("<f", raw))
            for value in values:
                if not math.isfinite(value):
                    raise ValueError("Nonfinite resource sample")
                self.sample_hash.update(struct.pack("<f", value if value else 0.0))
            self.decoded += len(values)
            yield values
        if self.decoded != self.properties["frames"] * self.properties["channels"]:
            raise ValueError("Resource decoded sample count mismatch")

    def measurement(self):
        return dict(
            **self.properties,
            decoded_samples=self.decoded,
            sha256=self.file_hash.hexdigest(),
            sample_sha256=self.sample_hash.hexdigest(),
        )

    def close(self):
        if self.stream is not None:
            self.stream.close()


def read_buffer_snapshot(path, checkpoint=lambda: None):
    reader = None
    try:
        reader = FloatInput(path)
        for _ in reader.blocks(checkpoint):
            pass
        return reader.measurement()
    except TimeoutError:
        raise
    except (OSError, struct.error) as exc:
        raise ValueError(
            "Invalid or unavailable float32 snapshot: " + str(exc)
        ) from exc
    finally:
        if reader:
            reader.close()


def compare_resource_state(reference, snapshot, expected, checkpoint=lambda: None):
    """Every float32 value is compared; ±0 equal, no epsilon or hash-only shortcut."""
    left = right = None
    try:
        left = FloatInput(reference, expected)
        right = FloatInput(snapshot)
        if left.properties != right.properties:
            raise ValueError("Resource metadata mismatch")
        a, b = left.blocks(checkpoint), right.blocks(checkpoint)
        while True:
            av, bv = next(a, None), next(b, None)
            if av is None and bv is None:
                break
            if av != bv:
                raise ValueError("Resource sample mismatch")
        return dict(
            matches=True,
            reference=left.measurement(),
            measured=right.measurement(),
            evidence_scope="initial-state",
            internal_history_proven=False,
            subsequent_dsp_proven=False,
        )
    except TimeoutError:
        raise
    except (OSError, struct.error) as exc:
        raise ValueError(
            "Invalid or unavailable resource evidence: " + str(exc)
        ) from exc
    finally:
        for reader in (left, right):
            if reader:
                reader.close()
