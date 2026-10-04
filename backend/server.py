"""VisionGuard laptop server: webcam -> YOLOv8 person detection + IoU tracking
-> human attributes (132 labels) -> danger rules -> web dashboard.

Same pipeline idea as the former Qualcomm RB3 C app, re-done for a laptop:
  capture thread   : reads the webcam, keeps only the newest frame
  detect thread    : YOLO + tracker every frame, draws boxes, encodes MJPEG
  attribute thread : runs the attribute model on the newest person job only,
                     so slow attribute inference never blocks the video
HTTP API (kept compatible with the C app): /stream_cam1, /dets, /api/person,
plus /api/tracks, /api/events, /api/rules and POST /api/analyze (single uploaded image).
The frontend/ folder is served at /.

Run:  python backend/server.py            then open http://localhost:8080/
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from attributes import AttributePipeline, crop_with_pad, head_box_from_keypoints, select_labels, to_payload
from behavior import BehaviorHistory, OcclusionMonitor, pose_flags
from rules import DangerResult, RuleEngine, RuleState

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DIR = ROOT / "frontend"
log = logging.getLogger("visionguard")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="VisionGuard laptop webcam server")
    p.add_argument("--camera", type=int, default=0, help="Webcam index (0 = built-in laptop camera).")
    p.add_argument("--source", default="", help="Optional video/image file instead of the webcam (looped, for demos/tests).")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--yolo", default=str(ROOT / "models" / "yolov8n-pose.pt"),
                   help="Pose model gives face keypoints for accurate mask/glasses/hat crops; plain yolov8n.pt also works.")
    p.add_argument("--conf", type=float, default=0.40, help="YOLO person confidence threshold.")
    p.add_argument("--iou", type=float, default=0.45, help="YOLO NMS IoU threshold.")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--attr-onnx", default=str(ROOT / "human_attr" / "model_68.onnx"),
                   help="Trained attribute model. If missing, CLIP zero-shot is used.")
    p.add_argument("--attr-meta", default=str(ROOT / "human_attr" / "model_68.onnx.json"))
    p.add_argument("--clip-model", default="openai/clip-vit-base-patch32")
    p.add_argument("--attr-interval", type=float, default=1.0, help="Seconds between attribute refreshes per person.")
    p.add_argument("--attr-ema", type=float, default=0.5, help="Weight of the newest attribute result (1 = no smoothing).")
    p.add_argument("--rule-interval", type=float, default=1.0, help="Seconds between rule evaluations per person.")
    p.add_argument("--min-person-w", type=float, default=60.0)
    p.add_argument("--min-person-h", type=float, default=80.0)
    p.add_argument("--web-dir", default=str(DEFAULT_WEB_DIR))
    p.add_argument("--rules", default=str(ROOT / "rules" / "rules.yaml"),
                   help="Rule file: rules.yaml (v2) or the legacy dangerous_attributes_rules.csv.")
    p.add_argument("--objects", default=str(ROOT / "models" / "yolov8n.pt"),
                   help="COCO YOLO for weapons/bags near each person ('' to disable).")
    p.add_argument("--no-cues", action="store_true", help="Disable CLIP cues (hood, face covered, full-face helmet).")
    p.add_argument("--events-dir", default=str(ROOT / "events"), help="Snapshots of suspicious persons.")
    return p.parse_args()


# --------------------------------------------------------------------------- #
# Tracking
# --------------------------------------------------------------------------- #
def iou(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


@dataclass
class Track:
    id: int
    bbox: list[float]
    score: float
    last_seen: float
    first_seen: float
    kps: np.ndarray | None = None            # pose keypoints [17, 3] (x, y, conf)
    probs: np.ndarray | None = None          # EMA-smoothed probabilities (132 attributes + extra cues)
    selected: dict[str, float] | None = None # post-processed attributes + cues -> prob
    active: dict[str, float] | None = None   # selected + behaviour/context labels -> prob (what rules see)
    history: BehaviorHistory = field(default_factory=BehaviorHistory)
    rule_time: float = 0.0
    attr_time: float = 0.0
    attr_bbox: list[float] | None = None
    attr_latency_ms: float = 0.0
    concealment: float = 0.0
    back_views: deque = field(default_factory=lambda: deque(maxlen=8))
    rule_state: RuleState = field(default_factory=RuleState)
    danger: DangerResult = field(default_factory=DangerResult)
    logged_rules: set = field(default_factory=set)


class IouTracker:
    def __init__(self, iou_thr: float = 0.3, max_age: float = 3.0):
        self.iou_thr, self.max_age = iou_thr, max_age
        self.tracks: dict[int, Track] = {}
        self._next = 1

    def update(self, dets: list[tuple[list[float], float, np.ndarray | None]], now: float) -> list[Track]:
        pairs = sorted(((iou(t.bbox, d[0]), tid, di) for tid, t in self.tracks.items() for di, d in enumerate(dets)),
                       reverse=True)
        used_t, used_d = set(), set()
        for score, tid, di in pairs:
            if score < self.iou_thr or tid in used_t or di in used_d:
                continue
            t = self.tracks[tid]
            t.bbox, t.score, t.kps, t.last_seen = dets[di][0], dets[di][1], dets[di][2], now
            used_t.add(tid)
            used_d.add(di)
        for di, (bbox, score, kps) in enumerate(dets):
            if di not in used_d:
                self.tracks[self._next] = Track(self._next, bbox, score, now, now, kps)
                self._next += 1
        for tid in [tid for tid, t in self.tracks.items() if now - t.last_seen > self.max_age]:
            del self.tracks[tid]
        return [t for t in self.tracks.values() if t.last_seen == now]


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
class Pipeline:
    def __init__(self, args: argparse.Namespace):
        from ultralytics import YOLO

        self.args = args
        self.lock = threading.Lock()
        self.stop = threading.Event()

        self.frame: np.ndarray | None = None
        self.frame_id = 0
        self.jpeg: bytes = b""
        self.jpeg_id = 0
        self.fps = 0.0
        self.yolo_ms = 0.0
        self.frame_wh = (args.width, args.height)
        self.camera_ok = False

        self.tracker = IouTracker()
        self.visible: list[Track] = []
        self.target_id: int | None = None
        self.events: list[dict] = []
        self.occlusion = OcclusionMonitor()
        self.scene: dict = {"camera_occluded": False}

        self.engine_lock = threading.Lock()   # attribute models are shared by the worker and /api/analyze
        self.job_cv = threading.Condition()
        self.job: tuple[int, np.ndarray, list[float], tuple | None, np.ndarray | None] | None = None
        self.attr_running = False

        log.info("Loading YOLO: %s", args.yolo)
        self.yolo = YOLO(args.yolo)
        self.rules = RuleEngine(Path(args.rules))
        log.info("Loaded %d danger rules from %s", len(self.rules.rules), args.rules)
        log.info("Loading attribute engine (onnx=%s exists=%s)", args.attr_onnx, Path(args.attr_onnx).is_file())
        self.engine = AttributePipeline(Path(args.attr_onnx), Path(args.attr_meta), args.clip_model,
                                        args.objects or None, use_cues=not args.no_cues)
        log.info("Attribute engine: %s", self.engine.name)
        Path(args.events_dir).mkdir(parents=True, exist_ok=True)

    # -- threads ----------------------------------------------------------- #
    def start(self):
        for fn in (self._capture_loop, self._detect_loop, self._attr_loop):
            threading.Thread(target=fn, daemon=True, name=fn.__name__).start()

    def _open_camera(self):
        if self.args.source:
            return cv2.VideoCapture(self.args.source)
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.args.camera, backend)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self.args.camera)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.args.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _capture_loop(self):
        still = cv2.imread(self.args.source) if self.args.source else None
        if still is not None:  # single image: replay it as a 15 fps "camera"
            while not self.stop.is_set():
                with self.lock:
                    self.frame, self.frame_id = still, self.frame_id + 1
                    self.frame_wh, self.camera_ok = (still.shape[1], still.shape[0]), True
                time.sleep(1 / 15)
            return
        cap = self._open_camera()
        while not self.stop.is_set():
            ok, frame = cap.read()
            if self.args.source:
                if not ok:  # loop the file
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                time.sleep(1 / 15)
            if not ok or frame is None:
                with self.lock:
                    self.camera_ok = False
                log.warning("Cannot read camera %d, retrying...", self.args.camera)
                cap.release()
                time.sleep(1.0)
                cap = self._open_camera()
                continue
            with self.lock:
                self.frame = frame
                self.frame_id += 1
                self.frame_wh = (frame.shape[1], frame.shape[0])
                self.camera_ok = True
        cap.release()

    def _detect_loop(self):
        last_id, t_prev = 0, time.perf_counter()
        while not self.stop.is_set():
            with self.lock:
                frame, fid = self.frame, self.frame_id
            if frame is None or fid == last_id:
                time.sleep(0.003)
                continue
            last_id = fid
            t0 = time.perf_counter()
            res = self.yolo(frame, classes=[0], conf=self.args.conf, iou=self.args.iou,
                            imgsz=self.args.imgsz, verbose=False)[0]
            yolo_ms = (time.perf_counter() - t0) * 1000.0
            boxes, confs = res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy()
            kps = res.keypoints.data.cpu().numpy() if res.keypoints is not None else [None] * len(boxes)
            dets = [(b.tolist(), float(s), k) for b, s, k in zip(boxes, confs, kps)]
            now = time.monotonic()
            scene = self.occlusion.update(frame, now, self.rules.behavior)
            with self.lock:
                visible = self.tracker.update(dets, now)
                self.visible = visible
                kp_conf = float(self.rules.behavior.get("kp_conf", 0.4))
                for t in visible:
                    t.history.add(now, t.bbox, self.frame_wh, pose_flags(t.kps, t.bbox, self.frame_wh, kp_conf))
                new_events = self._evaluate_rules(visible, now)
                self.target_id = self._pick_target(visible)
                self._schedule_attr(frame, visible, now)
                scene_started = scene["camera_occluded"] and not self.scene.get("camera_occluded")
                self.scene = scene
                annotated = self._draw(frame.copy(), visible)
            for t, bbox, labels in new_events:
                self._log_event(t, frame, bbox, labels)
            if scene_started:
                self._log_scene_event(frame, scene)
            if scene["camera_occluded"]:
                cv2.putText(annotated, "CAMERA OCCLUDED", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (60, 60, 235), 3, cv2.LINE_AA)
            ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
            t_now = time.perf_counter()
            dt, t_prev = t_now - t_prev, t_now
            with self.lock:
                if ok:
                    self.jpeg, self.jpeg_id = buf.tobytes(), self.jpeg_id + 1
                self.yolo_ms = yolo_ms
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt) if self.fps else 1.0 / max(dt, 1e-6)

    def _attr_loop(self):
        while not self.stop.is_set():
            with self.job_cv:
                while self.job is None and not self.stop.is_set():
                    self.job_cv.wait(0.5)
                if self.job is None:
                    continue
                tid, frame, bbox, head_box, kps = self.job
                self.job = None
                self.attr_running = True
            try:
                t0 = time.perf_counter()
                with self.engine_lock:
                    probs = self.engine.predict(frame, bbox, head_box, kps)
                latency = (time.perf_counter() - t0) * 1000.0
                self._apply_attr(tid, frame, bbox, probs, latency)
            except Exception:
                log.exception("Attribute inference failed")
            finally:
                with self.job_cv:
                    self.attr_running = False

    # -- helpers (called with self.lock held unless noted) ---------------- #
    def _valid_size(self, t: Track) -> bool:
        return (t.bbox[2] - t.bbox[0]) >= self.args.min_person_w and (t.bbox[3] - t.bbox[1]) >= self.args.min_person_h

    def _pick_target(self, visible: list[Track]) -> int | None:
        if not visible:
            return None
        dangerous = [t for t in visible if t.danger.is_dangerous]
        pool = dangerous or visible
        best = max(pool, key=lambda t: area(t.bbox))
        prev = next((t for t in pool if t.id == self.target_id), None)
        if prev is not None and area(prev.bbox) >= 0.7 * area(best.bbox):
            return prev.id  # sticky target, avoids flicker between similar people
        return best.id

    def _schedule_attr(self, frame: np.ndarray, visible: list[Track], now: float):
        with self.job_cv:
            if self.job is not None or self.attr_running:
                return
            due = [t for t in visible if self._valid_size(t) and (
                t.probs is None or now - t.attr_time >= self.args.attr_interval
                or (t.attr_bbox is not None and iou(t.bbox, t.attr_bbox) < 0.5))]
            if not due:
                return
            # Target first, then whoever has waited longest.
            due.sort(key=lambda t: (t.id != self.target_id, t.attr_time))
            t = due[0]
            self.job = (t.id, frame, list(t.bbox), head_box_from_keypoints(t.kps, t.bbox), t.kps)
            self.job_cv.notify()

    def _apply_attr(self, tid: int, frame: np.ndarray, bbox: list[float], probs: np.ndarray, latency: float):
        """Called from the attribute thread."""
        with self.lock:
            t = self.tracker.tracks.get(tid)
            if t is None:
                return
            a = self.args.attr_ema
            t.probs = probs if t.probs is None else a * probs + (1.0 - a) * t.probs
            t.attr_time, t.attr_bbox, t.attr_latency_ms = time.monotonic(), bbox, latency
            t.selected = select_labels(t.probs)
            t.back_views.append("viewpointBack" in t.selected)
            t.concealment = self.rules.concealment_score(t.selected)
            t.rule_time = 0.0  # evaluate rules on the next frame with the fresh attributes

    def _evaluate_rules(self, visible: list[Track], now: float) -> list[tuple]:
        """Rules run for every visible person at `rule_interval`, even before / without attributes,
        so behaviour rules (running, fast approach, pacing...) also cover people far from the camera."""
        events = []
        for t in visible:
            if now - t.rule_time < self.args.rule_interval:
                continue
            t.rule_time = now
            t.active = {**(t.selected or {}), **self._context_labels(t, now)}
            t.danger = self.rules.evaluate(t.active, t.rule_state)
            new_rules = {r["id"] for r in t.danger.matched} - t.logged_rules
            if new_rules:
                t.logged_rules |= new_rules
                events.append((t, list(t.bbox), sorted(t.active)))
        return events

    def _context_labels(self, t: Track, now: float) -> dict[str, float]:
        """Behaviour / scene facts usable in rules.yaml (lock held)."""
        ctx = self.rules.context
        out: dict[str, float] = t.history.labels(now, now - t.first_seen, self.rules.behavior)
        if t.concealment >= self.rules.conc_threshold:
            out["faceConcealedHigh"] = t.concealment
        dwell = now - t.first_seen
        if dwell >= float(ctx.get("loiter_seconds", 1e9)):
            out["loitering"] = 1.0
        if (dwell >= float(ctx.get("avoid_camera_min_seconds", 8)) and len(t.back_views) >= 4
                and sum(t.back_views) / len(t.back_views) >= float(ctx.get("avoid_camera_ratio", 0.7))):
            out["avoidingCamera"] = 1.0
        concealed = sum(1 for o in self.visible if o.concealment >= self.rules.concealed_threshold)
        if t.concealment >= self.rules.concealed_threshold and concealed >= int(ctx.get("group_min_persons", 2)):
            out["groupConcealed"] = 1.0
        return out

    def _log_event(self, t: Track, frame: np.ndarray, bbox: list[float], labels: list[str]):
        ts = time.strftime("%Y%m%d_%H%M%S")
        stem = f"{ts}_id{t.id}"
        crop = crop_with_pad(frame, bbox, 0.1)
        cv2.imwrite(str(Path(self.args.events_dir) / f"{stem}.jpg"), crop)
        event = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "track_id": t.id, "bbox": [round(v, 1) for v in bbox],
                 "labels": labels, "snapshot": f"{stem}.jpg", **t.danger.to_json()}
        (Path(self.args.events_dir) / f"{stem}.json").write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.lock:
            self.events.insert(0, event)
            del self.events[50:]
        log.warning("SUSPICIOUS person id=%d: %s", t.id, "; ".join(r["desc"] for r in event["matched_rules"]))

    def _log_scene_event(self, frame: np.ndarray, scene: dict):
        stem = time.strftime("%Y%m%d_%H%M%S") + "_scene"
        cv2.imwrite(str(Path(self.args.events_dir) / f"{stem}.jpg"), frame)
        event = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "track_id": None, "snapshot": f"{stem}.jpg",
                 "is_dangerous": True, "risk_level": "High", "scene": scene,
                 "matched_rules": [{"id": "S01", "category": "Camera Tampering", "risk": "High",
                                    "desc": "Camera bị che / mất hình", "confidence": 1.0}]}
        (Path(self.args.events_dir) / f"{stem}.json").write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.lock:
            self.events.insert(0, event)
            del self.events[50:]
        log.warning("CAMERA OCCLUDED (brightness=%.1f contrast=%.1f)", scene["brightness"], scene["contrast"])

    def _draw(self, img: np.ndarray, visible: list[Track], target_id: int | None = -1) -> np.ndarray:
        target_id = self.target_id if target_id == -1 else target_id
        for t in visible:
            x0, y0, x1, y1 = map(int, t.bbox)
            danger = t.danger.is_dangerous
            pending = bool(t.danger.pending) and not danger
            # red = alert, orange = rule seen but not yet confirmed, green = normal
            color = (60, 60, 235) if danger else (0, 165, 255) if pending else (90, 200, 60)
            thick = 3 if t.id == target_id else 2
            cv2.rectangle(img, (x0, y0), (x1, y1), color, thick)
            if danger:
                text = f"ID {t.id} {t.danger.risk_level.upper()} {t.danger.risk_score:.0%}"
            else:
                text = f"ID {t.id} {'checking' if pending else 'person'} {t.score:.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            ty = max(th + 6, y0)
            cv2.rectangle(img, (x0, ty - th - 6), (x0 + tw + 8, ty), color, -1)
            cv2.putText(img, text, (x0 + 4, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        return img

    # -- single image (upload mode) ------------------------------------- #
    def analyze_image(self, img: np.ndarray) -> dict:
        """Detect every person in one image, run attributes + rules (no temporal persistence)."""
        res = self.yolo(img, classes=[0], conf=self.args.conf, iou=self.args.iou, imgsz=self.args.imgsz, verbose=False)[0]
        boxes, confs = res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy()
        kps = res.keypoints.data.cpu().numpy() if res.keypoints is not None else [None] * len(boxes)
        now = time.monotonic()
        people: list[Track] = []
        for i, (b, sc, k) in enumerate(zip(boxes, confs, kps), start=1):
            t = Track(i, b.tolist(), float(sc), now, now, k)
            if self._valid_size(t):
                t0 = time.perf_counter()
                with self.engine_lock:
                    t.probs = self.engine.predict(img, t.bbox, head_box_from_keypoints(k, t.bbox), k)
                t.attr_latency_ms = (time.perf_counter() - t0) * 1000.0
                t.selected = select_labels(t.probs)
                t.concealment = self.rules.concealment_score(t.selected)
                t.active = dict(t.selected)
                t.attr_time = now
                # Single image: only instant pose cues (no time axis for running / pacing / looking around)
                flags = pose_flags(k, t.bbox, (img.shape[1], img.shape[0]), float(self.rules.behavior.get("kp_conf", 0.4)))
                if flags["hands_face"]:
                    t.active["handsCoveringFace"] = 0.8
                if flags["arms_raised"]:
                    t.active["armsRaised"] = 0.8
            people.append(t)
        n_concealed = sum(t.concealment >= self.rules.concealed_threshold for t in people)
        for t in people:
            if t.active is None:
                continue
            if t.concealment >= self.rules.conc_threshold:
                t.active["faceConcealedHigh"] = t.concealment
            if t.concealment >= self.rules.concealed_threshold and n_concealed >= int(self.rules.context.get("group_min_persons", 2)):
                t.active["groupConcealed"] = 1.0
            t.danger = self.rules.evaluate(t.active, instant=True)
        ranked = sorted(people, key=lambda t: (t.danger.risk_score, area(t.bbox)), reverse=True)
        target = ranked[0].id if ranked else None
        annotated = self._draw(img.copy(), people, target)
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return {
            "frame": {"w": img.shape[1], "h": img.shape[0]},
            "image": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else "",
            "target_id": target,
            "persons": [self.track_json(t, now) for t in ranked],
        }

    # -- API payloads ---------------------------------------------------- #
    def track_json(self, t: Track, now: float) -> dict:
        has_attr = t.selected is not None
        out = {
            "person": {"valid": True, "track_id": t.id, "bbox": [round(v, 1) for v in t.bbox], "score": round(t.score, 3),
                       "dwell_s": round(now - t.first_seen, 1)},
            "attr": {"valid": has_attr, "stale": has_attr and now - t.attr_time > 3.0,
                     "latency_ms": round(t.attr_latency_ms, 1), "engine": self.engine.name},
        }
        out.update(to_payload(t.active or {}))   # behaviour labels exist even before attributes
        if not has_attr:
            out["attr"]["reason"] = "pending" if self._valid_size(t) else "bbox_too_small"
        out["danger"] = t.danger.to_json()
        return out

    def person_json(self) -> dict:
        now = time.monotonic()
        with self.lock:
            target = next((t for t in self.visible if t.id == self.target_id), None)
            base = {"frame": {"w": self.frame_wh[0], "h": self.frame_wh[1]}, "camera_ok": self.camera_ok,
                    "tracks_count": len(self.visible),
                    "suspicious_count": sum(t.danger.is_dangerous for t in self.visible), "scene": dict(self.scene)}
            if target is None:
                return {**base, "person": {"valid": False},
                        "attr": {"valid": False, "reason": "no_person", "engine": self.engine.name},
                        "attributes_by_head": {}, "positive_attributes": [], "danger": DangerResult().to_json()}
            return {**base, **self.track_json(target, now)}

    def tracks_json(self) -> dict:
        now = time.monotonic()
        with self.lock:
            return {"target_id": self.target_id, "tracks": [self.track_json(t, now) for t in self.visible]}

    def dets_json(self) -> dict:
        with self.lock:
            return {"frame_id": self.frame_id, "fps": round(self.fps, 2), "yolo_latency_ms": round(self.yolo_ms, 2),
                    "camera_ok": self.camera_ok, "scene": dict(self.scene),
                    "frame": {"w": self.frame_wh[0], "h": self.frame_wh[1]},
                    "dets": [{"cls": "person", "cls_id": 0, "track_id": t.id, "score": round(t.score, 3),
                              "x": round(t.bbox[0], 1), "y": round(t.bbox[1], 1), "r": round(t.bbox[2], 1),
                              "b": round(t.bbox[3], 1), "dangerous": t.danger.is_dangerous} for t in self.visible]}

    def mjpeg(self):
        last = 0
        while not self.stop.is_set():
            with self.lock:
                jid, data = self.jpeg_id, self.jpeg
            if jid == last or not data:
                time.sleep(0.01)
                continue
            last = jid
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n"


def build_app(pipe: Pipeline, web_dir: Path) -> FastAPI:
    app = FastAPI(title="VisionGuard laptop")
    nocache = {"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}

    @app.get("/stream_cam1")
    def stream():
        return StreamingResponse(pipe.mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/dets")
    def dets():
        return JSONResponse(pipe.dets_json(), headers=nocache)

    @app.get("/api/person")
    @app.get("/current_attributes.json")  # legacy file name polled by older app.js
    def person():
        return JSONResponse(pipe.person_json(), headers=nocache)

    @app.get("/api/tracks")
    def tracks():
        return JSONResponse(pipe.tracks_json(), headers=nocache)

    @app.get("/api/rules")
    def rules():
        r = pipe.rules
        return JSONResponse({"source": str(r.path), "groups": r.groups, "context": r.context,
                             "rules": [vars(x) for x in r.rules]}, headers=nocache)

    @app.post("/api/analyze")
    async def analyze(file: UploadFile = File(...)):
        data = np.frombuffer(await file.read(), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "Không đọc được ảnh (hỗ trợ JPG / PNG / BMP / WEBP)")
        if max(img.shape[:2]) > 1920:  # keep CPU time reasonable
            s = 1920 / max(img.shape[:2])
            img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        return JSONResponse(await run_in_threadpool(pipe.analyze_image, img), headers=nocache)

    @app.get("/api/events")
    def events():
        with pipe.lock:
            return JSONResponse(list(pipe.events), headers=nocache)

    @app.get("/")
    def root():
        return RedirectResponse("/select.html")

    app.mount("/events", StaticFiles(directory=pipe.args.events_dir), name="events")
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    web_dir = Path(args.web_dir)
    if not (web_dir / "realtime.html").is_file():
        raise SystemExit(f"Frontend not found in {web_dir} (use --web-dir)")
    pipe = Pipeline(args)
    pipe.start()
    log.info("Open http://%s:%d/realtime.html", args.host, args.port)
    try:
        uvicorn.run(build_app(pipe, web_dir), host=args.host, port=args.port, log_level="warning")
    finally:
        pipe.stop.set()


if __name__ == "__main__":
    main()
