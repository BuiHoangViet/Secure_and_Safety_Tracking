"""Behaviour attributes from pose keypoints + track history (geometry, no extra model).

Per frame  : pose_flags()        -> hands on face, arms raised, head yaw / pitch, at frame edge
Per track  : BehaviorHistory     -> time-window labels used by rules.yaml
               handsCoveringFace, lookingAround, hidingFaceDown, armsRaised,
               running, fastApproach, pacing, edgeLurking
Per scene  : OcclusionMonitor    -> cameraOcclusion (lens covered / blacked out)

COCO keypoints: 0 nose, 1/2 eyes, 3/4 ears, 5/6 shoulders, 7/8 elbows, 9/10 wrists, 11/12 hips.
All thresholds come from the `behavior:` section of rules.yaml (defaults below).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

DEFAULTS = {
    "kp_conf": 0.4,
    "hands_face_window": 3.0, "hands_face_ratio": 0.6,
    "look_window": 6.0, "look_yaw": 0.25, "look_switches": 3,
    "head_down_window": 6.0, "head_down_ratio": 0.7, "head_down_pitch": 0.45,
    "arms_window": 1.5, "arms_ratio": 0.5,
    "run_speed": 1.5,                       # body heights per second
    "approach_window": 1.5, "approach_growth": 1.8, "approach_min_area": 0.10,
    "pacing_window": 20.0, "pacing_reversals": 3, "pacing_step": 0.3, "pacing_min_dwell": 15.0,
    "edge_window": 10.0, "edge_ratio": 0.8, "edge_min_dwell": 10.0,
    "occlusion_std": 10.0, "occlusion_dark": 12.0, "occlusion_seconds": 2.0,
}


def _pt(kps, i, conf):
    return kps[i, :2] if kps is not None and kps[i, 2] >= conf else None


def pose_flags(kps: np.ndarray | None, bbox, frame_wh, conf: float = 0.4) -> dict:
    """Instant (single frame) flags; also usable for one uploaded image."""
    W, H = frame_wh
    x0, y0, x1, y1 = bbox
    out = {"hands_face": False, "arms_raised": False, "yaw": None, "pitch": None,
           "edge": (x0 <= 0.02 * W or x1 >= 0.98 * W) and (x1 - x0) < 0.5 * W}
    if kps is None or len(kps) < 11:
        return out
    nose = _pt(kps, 0, conf)
    eyes = [p for p in (_pt(kps, 1, conf), _pt(kps, 2, conf)) if p is not None]
    ears = [p for p in (_pt(kps, 3, conf), _pt(kps, 4, conf)) if p is not None]
    sh = [p for p in (_pt(kps, 5, conf), _pt(kps, 6, conf)) if p is not None]
    wrists = [p for p in (_pt(kps, 9, conf), _pt(kps, 10, conf)) if p is not None]

    face_pts = ([nose] if nose is not None else []) + eyes + ears
    sh_w = abs(float(sh[0][0] - sh[1][0])) if len(sh) == 2 else 0.0
    if face_pts:
        fc = np.mean(face_pts, axis=0)
        face_size = max(0.18 * (x1 - x0), 0.45 * sh_w,
                        2.5 * abs(float(eyes[0][0] - eyes[1][0])) if len(eyes) == 2 else 0.0)
        # Hand on / in front of the face
        out["hands_face"] = any(np.linalg.norm(w - fc) < 0.9 * face_size for w in wrists)
    elif len(sh) == 2 and wrists:
        # Face keypoints lost (often because hands cover it): wrist above the shoulder line, between shoulders
        top = min(sh[0][1], sh[1][1])
        lo, hi = sorted((sh[0][0], sh[1][0]))
        out["hands_face"] = any(w[1] < top and lo <= w[0] <= hi for w in wrists)

    # Both wrists above the head (or well above shoulders)
    if len(wrists) == 2:
        ref = nose[1] if nose is not None else (min(s[1] for s in sh) - 0.3 * sh_w if sh else None)
        out["arms_raised"] = ref is not None and all(w[1] < ref for w in wrists)

    # Head yaw: nose offset from shoulder (or ear) midpoint, normalised
    if nose is not None:
        if len(sh) == 2 and sh_w > 1:
            out["yaw"] = float((nose[0] - (sh[0][0] + sh[1][0]) / 2) / sh_w)
        elif len(ears) == 2:
            d = abs(float(ears[0][0] - ears[1][0]))
            if d > 1:
                out["yaw"] = float((nose[0] - (ears[0][0] + ears[1][0]) / 2) / d)
        # Head pitch: nose below the ear line = looking down
        if ears:
            ref_d = abs(float(ears[0][0] - ears[1][0])) if len(ears) == 2 else (
                abs(float(eyes[0][0] - eyes[1][0])) * 2 if len(eyes) == 2 else 0.0)
            if ref_d > 1:
                out["pitch"] = float((nose[1] - np.mean([e[1] for e in ears])) / ref_d)
    return out


@dataclass
class Sample:
    t: float
    cx: float
    cy: float
    h: float
    area: float          # fraction of the frame
    flags: dict


class BehaviorHistory:
    def __init__(self, maxlen: int = 600):
        self.samples: deque[Sample] = deque(maxlen=maxlen)

    def add(self, now: float, bbox, frame_wh, flags: dict):
        x0, y0, x1, y1 = bbox
        W, H = frame_wh
        self.samples.append(Sample(now, (x0 + x1) / 2, (y0 + y1) / 2, max(1.0, y1 - y0),
                                   (x1 - x0) * (y1 - y0) / float(W * H), flags))

    def _window(self, now: float, seconds: float) -> list[Sample]:
        return [s for s in self.samples if now - s.t <= seconds]

    @staticmethod
    def _ratio(samples: list[Sample], key: str) -> float:
        return sum(bool(s.flags.get(key)) for s in samples) / len(samples) if samples else 0.0

    def labels(self, now: float, dwell: float, cfg: dict) -> dict[str, float]:
        c = {**DEFAULTS, **(cfg or {})}
        out: dict[str, float] = {}

        w = self._window(now, c["hands_face_window"])
        if len(w) >= 5 and (r := self._ratio(w, "hands_face")) >= c["hands_face_ratio"]:
            out["handsCoveringFace"] = r

        w = self._window(now, c["arms_window"])
        if len(w) >= 3 and (r := self._ratio(w, "arms_raised")) >= c["arms_ratio"]:
            out["armsRaised"] = r

        # Looking around: head turns left <-> right repeatedly
        w = [s for s in self._window(now, c["look_window"]) if s.flags.get("yaw") is not None]
        if len(w) >= 10:
            states = [-1 if s.flags["yaw"] < -c["look_yaw"] else 1 for s in w if abs(s.flags["yaw"]) >= c["look_yaw"]]
            switches = sum(1 for a, b in zip(states, states[1:]) if a != b)
            if switches >= c["look_switches"]:
                out["lookingAround"] = min(1.0, switches / (c["look_switches"] + 1))

        # Head kept down (hiding face from camera)
        w = [s for s in self._window(now, c["head_down_window"]) if s.flags.get("pitch") is not None]
        if len(w) >= 10:
            r = sum(s.flags["pitch"] > c["head_down_pitch"] for s in w) / len(w)
            if r >= c["head_down_ratio"]:
                out["hidingFaceDown"] = r

        # Speed in body heights / second over the last second
        w = self._window(now, 1.0)
        if len(w) >= 4 and w[-1].t - w[0].t > 0.4:
            h = float(np.median([s.h for s in w]))
            dist = sum(np.hypot(b.cx - a.cx, b.cy - a.cy) for a, b in zip(w, w[1:]))
            speed = dist / h / (w[-1].t - w[0].t)
            if speed >= c["run_speed"]:
                out["running"] = min(1.0, speed / (2 * c["run_speed"]))

        # Fast approach: box grows quickly toward the camera
        w = self._window(now, c["approach_window"])
        if len(w) >= 4 and w[0].area > 0:
            growth = w[-1].area / w[0].area
            if growth >= c["approach_growth"] and w[-1].area >= c["approach_min_area"]:
                out["fastApproach"] = min(1.0, growth / (2 * c["approach_growth"]))

        # Pacing: walking back and forth while staying around
        if dwell >= c["pacing_min_dwell"]:
            w = self._window(now, c["pacing_window"])
            if len(w) >= 20:
                h = float(np.median([s.h for s in w]))
                reversals, direction, anchor = 0, 0, w[0].cx
                for s in w[1:]:
                    d = s.cx - anchor
                    if abs(d) >= c["pacing_step"] * h:
                        new_dir = 1 if d > 0 else -1
                        if direction and new_dir != direction:
                            reversals += 1
                        direction, anchor = new_dir, s.cx
                if reversals >= c["pacing_reversals"]:
                    out["pacing"] = min(1.0, reversals / (c["pacing_reversals"] + 1))

        # Lurking at the frame edge (half hidden, peeking)
        if dwell >= c["edge_min_dwell"]:
            w = self._window(now, c["edge_window"])
            if len(w) >= 10 and (r := self._ratio(w, "edge")) >= c["edge_ratio"]:
                out["edgeLurking"] = r
        return {k: float(v) for k, v in out.items()}


class OcclusionMonitor:
    """Scene-level: lens covered / camera blacked out for a few seconds."""

    def __init__(self):
        self.since: float | None = None

    def update(self, frame_bgr: np.ndarray, now: float, cfg: dict) -> dict:
        c = {**DEFAULTS, **(cfg or {})}
        small = cv2.cvtColor(cv2.resize(frame_bgr, (64, 36)), cv2.COLOR_BGR2GRAY)
        mean, std = float(small.mean()), float(small.std())
        bad = std < c["occlusion_std"] or mean < c["occlusion_dark"]
        if not bad:
            self.since = None
        elif self.since is None:
            self.since = now
        occluded = self.since is not None and now - self.since >= c["occlusion_seconds"]
        return {"camera_occluded": occluded, "since_s": round(now - self.since, 1) if self.since else 0.0,
                "brightness": round(mean, 1), "contrast": round(std, 1)}
