"""Full bounded PCM16 measurement, independent of acceptance policy."""

import hashlib
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
    except (OSError, EOFError, wave.Error, struct.error) as exc:
        raise ValueError("Invalid or unavailable WAV: " + str(exc)) from exc
