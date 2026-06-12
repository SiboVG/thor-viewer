import cv2
import numpy as np

# Colormap used for the temperature legend gradient. Inferno roughly matches
# the orange/purple palette the Thor bakes into its video stream.
LEGEND_COLORMAP = cv2.COLORMAP_INFERNO

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def draw_crosshair(frame: np.ndarray, copy: bool = True) -> np.ndarray:
    out = frame.copy() if copy else frame

    height, width = out.shape[:2]
    cx = width // 2
    cy = height // 2

    cv2.line(out, (cx - 20, cy), (cx + 20, cy), (255, 255, 255), 1)
    cv2.line(out, (cx, cy - 20), (cx, cy + 20), (255, 255, 255), 1)

    return out


def draw_recording_dot(frame: np.ndarray, copy: bool = True) -> np.ndarray:
    out = frame.copy() if copy else frame

    height, width = out.shape[:2]
    cv2.circle(out, (width - 20, 20), 8, (0, 0, 255), -1)

    return out


def _format_temperature(value: float) -> str:
    return f"{value:.1f}C"


def _put_label(
    frame: np.ndarray,
    text: str,
    anchor: tuple[int, int],
    align: str = "left",
    scale: float = 0.5,
    text_color: tuple[int, int, int] = (255, 255, 255),
    thickness: int = 1,
) -> None:
    """Draw text with a dark translucent background for legibility.

    ``anchor`` is the top-left of the text box unless ``align`` is "center"
    (anchor is the top-center) or "right" (anchor is the top-right).
    """
    (text_w, text_h), baseline = cv2.getTextSize(text, _FONT, scale, thickness)
    pad = 3

    box_w = text_w + 2 * pad
    box_h = text_h + baseline + 2 * pad

    x, y = anchor
    if align == "center":
        x -= box_w // 2
    elif align == "right":
        x -= box_w

    height, width = frame.shape[:2]
    x = max(0, min(x, width - box_w))
    y = max(0, min(y, height - box_h))

    box = frame[y : y + box_h, x : x + box_w]
    if box.size:
        cv2.addWeighted(box, 0.4, np.zeros_like(box), 0.0, 0.0, dst=box)

    text_origin = (x + pad, y + pad + text_h)
    cv2.putText(
        frame, text, text_origin, _FONT, scale, text_color, thickness, cv2.LINE_AA
    )


def draw_temperature_gradient_bar(
    frame: np.ndarray,
    min_celsius: float,
    max_celsius: float,
    copy: bool = True,
) -> np.ndarray:
    """Draw a vertical min-max temperature legend on the left edge."""
    out = frame.copy() if copy else frame
    height = out.shape[0]

    bar_x = 14
    bar_w = 16
    bar_top = 44
    bar_bottom = height - 44
    bar_h = bar_bottom - bar_top
    if bar_h <= 0:
        return out

    # 255 (hot color) at the top, 0 (cold color) at the bottom.
    ramp = np.linspace(255, 0, bar_h, dtype=np.uint8).reshape(-1, 1)
    ramp = np.repeat(ramp, bar_w, axis=1)
    colored = cv2.applyColorMap(ramp, LEGEND_COLORMAP)

    out[bar_top:bar_bottom, bar_x : bar_x + bar_w] = colored
    cv2.rectangle(
        out,
        (bar_x - 1, bar_top - 1),
        (bar_x + bar_w, bar_bottom),
        (255, 255, 255),
        1,
    )

    _put_label(
        out,
        _format_temperature(max_celsius),
        (bar_x - 1, bar_top - 18),
        align="left",
    )
    _put_label(
        out,
        _format_temperature(min_celsius),
        (bar_x - 1, bar_bottom + 4),
        align="left",
    )

    return out


def draw_center_temperature_label(
    frame: np.ndarray,
    center_celsius: float,
    copy: bool = True,
) -> np.ndarray:
    """Draw the center-point temperature centered along the top edge."""
    out = frame.copy() if copy else frame
    width = out.shape[1]

    _put_label(
        out,
        f"Center {_format_temperature(center_celsius)}",
        (width // 2, 10),
        align="center",
        scale=0.6,
    )

    return out


def draw_temperature_point_marker(
    frame: np.ndarray,
    position: tuple[int, int],
    celsius: float,
    color: tuple[int, int, int],
    label_prefix: str,
    copy: bool = True,
) -> np.ndarray:
    """Mark a temperature point (min or max) with a crosshair and value."""
    out = frame.copy() if copy else frame
    height, width = out.shape[:2]

    x, y = position
    x = max(0, min(int(x), width - 1))
    y = max(0, min(int(y), height - 1))

    # Crosshair with a dark outline so it reads on any background.
    cv2.drawMarker(out, (x, y), (0, 0, 0), cv2.MARKER_CROSS, 16, 3, cv2.LINE_AA)
    cv2.drawMarker(out, (x, y), color, cv2.MARKER_CROSS, 14, 1, cv2.LINE_AA)

    text = f"{label_prefix} {_format_temperature(celsius)}"
    label_y = y + 8 if y < height - 28 else y - 22
    _put_label(out, text, (x + 8, label_y), align="left", text_color=color)

    return out
