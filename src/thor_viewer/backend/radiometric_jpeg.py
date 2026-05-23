from dataclasses import dataclass
from pathlib import Path
import json

import numpy as np


THERMAL_WIDTH = 256
THERMAL_HEIGHT = 192
THERMAL_PIXELS = THERMAL_WIDTH * THERMAL_HEIGHT
THERMAL_BYTES = THERMAL_PIXELS * 4


@dataclass(frozen=True)
class RadiometricImage:
    preview_jpeg: bytes
    temperature: np.ndarray
    metadata: dict

    def temperature_at_thermal_xy(self, x: int, y: int) -> float | None:
        if x < 0 or x >= THERMAL_WIDTH:
            return None
        if y < 0 or y >= THERMAL_HEIGHT:
            return None

        value = float(self.temperature[y, x])

        # Filter invalid/sentinel values.
        if value < -40 or value > 600:
            return None

        return value

    def temperature_at_preview_xy(
        self,
        x: int,
        y: int,
        preview_width: int = 640,
        preview_height: int = 480,
    ) -> float | None:
        tx = round(x * (THERMAL_WIDTH - 1) / (preview_width - 1))
        ty = round(y * (THERMAL_HEIGHT - 1) / (preview_height - 1))

        return self.temperature_at_thermal_xy(tx, ty)

    def valid_temperature_values(self) -> np.ndarray:
        return self.temperature[
            (self.temperature > -40.0) & (self.temperature < 600.0)
        ]

    def min_temperature(self) -> float | None:
        valid = self.valid_temperature_values()
        if valid.size == 0:
            return None
        return float(valid.min())

    def max_temperature(self) -> float | None:
        valid = self.valid_temperature_values()
        if valid.size == 0:
            return None
        return float(valid.max())


def load_radiometric_jpeg(path: str | Path) -> RadiometricImage:
    data = Path(path).read_bytes()

    eoi = data.rfind(b"\xff\xd9")
    if eoi < 0:
        raise ValueError("JPEG EOI marker not found")

    preview_jpeg = data[: eoi + 2]
    trailer = data[eoi + 2 :]

    if len(trailer) < THERMAL_BYTES:
        raise ValueError(
            f"Trailer too small for {THERMAL_WIDTH}x{THERMAL_HEIGHT} float32 frame"
        )

    temperature = np.frombuffer(
        trailer[:THERMAL_BYTES],
        dtype="<f4",
    ).reshape(THERMAL_HEIGHT, THERMAL_WIDTH)

    metadata = _extract_json_metadata(trailer)

    return RadiometricImage(
        preview_jpeg=preview_jpeg,
        temperature=temperature,
        metadata=metadata,
    )


def _extract_json_metadata(trailer: bytes) -> dict:
    json_start = trailer.find(b"{", THERMAL_BYTES)
    if json_start < 0:
        return {}

    depth = 0

    for i in range(json_start, len(trailer)):
        byte = trailer[i]

        if byte == ord("{"):
            depth += 1
        elif byte == ord("}"):
            depth -= 1

            if depth == 0:
                json_bytes = trailer[json_start : i + 1]
                return json.loads(json_bytes.decode("utf-8", errors="replace"))

    return {}
