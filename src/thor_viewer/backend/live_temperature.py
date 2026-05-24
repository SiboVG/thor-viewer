from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thor_viewer.backend.temperature_provider import TemperatureProvider


LIVE_THERMAL_WIDTH = 256
LIVE_THERMAL_HEIGHT = 192
LIVE_THERMAL_PIXELS = LIVE_THERMAL_WIDTH * LIVE_THERMAL_HEIGHT
LIVE_THERMAL_BYTES = LIVE_THERMAL_PIXELS * 2

# Thor live UVC temperature packets contain a 2-byte UVC payload header followed
# by this 10-byte marker, then 256x192 little-endian uint16 Kelvin*10 values.
UVC_PAYLOAD_HEADER_BYTES = 2
THOR_TEMP_HEADER = bytes.fromhex("ff00ff00ff00ff00ff00")
THOR_TEMP_PACKET_DATA_BYTES = (
    UVC_PAYLOAD_HEADER_BYTES + len(THOR_TEMP_HEADER) + LIVE_THERMAL_BYTES
)

MIN_VALID_CELSIUS = -40.0
MAX_VALID_CELSIUS = 600.0


@dataclass(frozen=True)
class LiveTemperatureFrame(TemperatureProvider):
    k10: np.ndarray
    marker_offset: int | None = None
    payload_offset: int | None = None
    is_partial: bool = False

    def __post_init__(self) -> None:
        k10 = np.asarray(self.k10, dtype="<u2")
        if k10.ndim != 2:
            raise ValueError("Live temperature frame must be a 2D array")
        if k10.shape[1] != LIVE_THERMAL_WIDTH:
            raise ValueError(
                f"Live temperature frame width must be {LIVE_THERMAL_WIDTH}"
            )
        if k10.shape[0] > LIVE_THERMAL_HEIGHT:
            raise ValueError(
                f"Live temperature frame height cannot exceed {LIVE_THERMAL_HEIGHT}"
            )

        object.__setattr__(self, "k10", k10)

    @property
    def temperature(self) -> np.ndarray:
        return celsius_from_k10(self.k10)

    def temperature_at_thermal_xy(self, x: int, y: int) -> float | None:
        if x < 0 or x >= LIVE_THERMAL_WIDTH:
            return None
        if y < 0 or y >= self.k10.shape[0]:
            return None

        value = float(self.k10[y, x]) / 10.0 - 273.15
        if value < MIN_VALID_CELSIUS or value > MAX_VALID_CELSIUS:
            return None

        return value

    def temperature_at_preview_xy(
        self,
        x: int,
        y: int,
        preview_width: int,
        preview_height: int,
    ) -> float | None:
        thermal_x, thermal_y = preview_to_thermal_xy(
            x,
            y,
            preview_width,
            preview_height,
        )
        return self.temperature_at_thermal_xy(thermal_x, thermal_y)

    def valid_temperature_values(self) -> np.ndarray:
        temperature = self.temperature
        return temperature[
            (temperature > MIN_VALID_CELSIUS) & (temperature < MAX_VALID_CELSIUS)
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

    def min_temperature_position(self) -> tuple[int, int] | None:
        return _extreme_temperature_position(self.temperature, use_min=True)

    def max_temperature_position(self) -> tuple[int, int] | None:
        return _extreme_temperature_position(self.temperature, use_min=False)


def parse_live_temperature_packet(
    data: bytes,
    allow_partial: bool = False,
) -> LiveTemperatureFrame:
    marker_offset = find_thor_temp_header(data)
    payload_offset = marker_offset + len(THOR_TEMP_HEADER)
    available = max(0, len(data) - payload_offset)

    if available < LIVE_THERMAL_BYTES and not allow_partial:
        raise ValueError(
            "Incomplete temperature payload: "
            f"need {LIVE_THERMAL_BYTES} bytes after offset 0x{payload_offset:x}, "
            f"have {available}. This usually means the USBPcap/Wireshark "
            "packet was captured with a 65535-byte snapshot limit. Recapture "
            "with snapshot length >= 98343."
        )

    payload = data[payload_offset : payload_offset + LIVE_THERMAL_BYTES]
    if allow_partial and len(payload) < LIVE_THERMAL_BYTES:
        complete_pixels = len(payload) // 2
        complete_rows = complete_pixels // LIVE_THERMAL_WIDTH
        payload = payload[: complete_rows * LIVE_THERMAL_WIDTH * 2]
        if not payload:
            raise ValueError("No complete thermal rows were found")

    return parse_live_temperature_payload(
        payload,
        marker_offset=marker_offset,
        payload_offset=payload_offset,
        is_partial=len(payload) != LIVE_THERMAL_BYTES,
    )


def parse_live_temperature_payload(
    payload: bytes,
    marker_offset: int | None = None,
    payload_offset: int | None = None,
    is_partial: bool = False,
) -> LiveTemperatureFrame:
    if len(payload) % 2:
        raise ValueError("Temperature payload has an odd byte count")
    if len(payload) > LIVE_THERMAL_BYTES:
        raise ValueError(
            f"Temperature payload is larger than {LIVE_THERMAL_BYTES} bytes"
        )
    if len(payload) % (LIVE_THERMAL_WIDTH * 2):
        raise ValueError("Temperature payload does not contain complete rows")

    rows = len(payload) // (LIVE_THERMAL_WIDTH * 2)
    if rows == 0:
        raise ValueError("Temperature payload is empty")
    if rows != LIVE_THERMAL_HEIGHT and not is_partial:
        raise ValueError(
            f"Temperature payload must contain {LIVE_THERMAL_HEIGHT} rows"
        )

    k10 = np.frombuffer(payload, dtype="<u2").reshape(rows, LIVE_THERMAL_WIDTH)
    return LiveTemperatureFrame(
        k10=k10,
        marker_offset=marker_offset,
        payload_offset=payload_offset,
        is_partial=is_partial,
    )


def find_thor_temp_header(data: bytes) -> int:
    marker_offset = data.find(THOR_TEMP_HEADER)
    if marker_offset < 0:
        raise ValueError("Thor temp header ff00ff00ff00ff00ff00 was not found")
    return marker_offset


def celsius_from_k10(k10: np.ndarray) -> np.ndarray:
    return np.asarray(k10, dtype=np.float32) / 10.0 - 273.15


def preview_to_thermal_xy(
    x: int,
    y: int,
    preview_width: int,
    preview_height: int,
) -> tuple[int, int]:
    if preview_width <= 0 or preview_height <= 0:
        raise ValueError("Preview dimensions must be positive")

    thermal_x = min(
        LIVE_THERMAL_WIDTH - 1,
        max(0, x * LIVE_THERMAL_WIDTH // preview_width),
    )
    thermal_y = min(
        LIVE_THERMAL_HEIGHT - 1,
        max(0, y * LIVE_THERMAL_HEIGHT // preview_height),
    )
    return thermal_x, thermal_y


def _extreme_temperature_position(
    temperature: np.ndarray,
    use_min: bool,
) -> tuple[int, int] | None:
    valid = (temperature > MIN_VALID_CELSIUS) & (temperature < MAX_VALID_CELSIUS)
    if not np.any(valid):
        return None

    sentinel = np.inf if use_min else -np.inf
    masked = np.where(valid, temperature, sentinel)
    flat_index = int(np.argmin(masked) if use_min else np.argmax(masked))
    y, x = np.unravel_index(flat_index, temperature.shape)
    return int(x), int(y)
