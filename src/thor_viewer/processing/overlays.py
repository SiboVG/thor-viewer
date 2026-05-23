import cv2
import numpy as np


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
