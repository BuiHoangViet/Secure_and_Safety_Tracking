"""Human attribute recognition (132 labels / 18 heads) for laptop CPU/GPU.

Head table and post-processing are ported 1:1 from the RB3 C app
(cam_yolo_attr_web.c of the former Qualcomm RB3 deployment) so the JSON output matches
what the frontend already understands.

Two engines share the same label space:
  * OnnxAttrEngine - the original ResNet18 (human_attr/model_68.onnx), exact port
    of the NPU preprocessing. Used automatically when the file exists.
  * ClipAttrEngine - zero-shot CLIP fallback when the trained model is missing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class AttrHead:
    name: str
    offset: int
    threshold: float
    exclusive: bool
    nothing_idx: int
    labels: tuple[str, ...]

    @property
    def dim(self) -> int:
        return len(self.labels)


def _head(name, offset, threshold, exclusive, nothing_idx, labels):
    return AttrHead(name, offset, threshold, bool(exclusive), nothing_idx, tuple(labels))


COLORS = ["Black", "Grey", "White", "Brown", "Red", "Pink", "Yellow", "Orange", "Green", "Blue", "Purple"]

ATTR_HEADS: tuple[AttrHead, ...] = (
    _head("age", 0, 0.50, 1, -1, ["personalLess15", "personalLess30", "personalLess45", "personalLess60", "personalLarger60"]),
    _head("gender", 5, 0.50, 1, -1, ["personalMale", "personalFemale"]),
    _head("body", 7, 0.50, 1, -1, ["bodyFull", "bodyUpperHalf", "bodyLowerHalf"]),
    _head("accessory", 10, 0.45, 0, 1, ["accessoryMuffler", "accessoryNothing", "accessoryHeadphone", "accessoryHairBand", "accessoryKerchief"]),
    _head("hat_type", 15, 0.45, 1, -1, ["hatNone", "hatCap", "hatBeanie", "hatHelmet", "hatOthers"]),
    _head("hat_color", 20, 0.35, 1, -1, [f"hat{c}" for c in COLORS]),
    _head("mask_type", 31, 0.45, 1, -1, ["maskNone", "maskSurgical", "maskClothN95"]),
    _head("glasses_type", 34, 0.45, 1, -1, ["glassesNone", "glassesEyeglasses", "glassesSunglasses", "glassesOthers"]),
    _head("carrying", 38, 0.45, 0, 3, ["carryingBackpack", "carryingOther", "carryingMessengerBag", "carryingNothing", "carryingPlasticBags", "carryingBabyBuggy", "carryingShoppingTro", "carryingUmbrella", "carryingFolder", "carryingLuggageCase", "carryingSuitcase"]),
    _head("hair_style", 49, 0.50, 1, -1, ["hairShort", "hairLong", "hairBald"]),
    _head("hair_color", 52, 0.50, 1, -1, [f"hair{c}" for c in COLORS]),
    _head("upper_body_style", 63, 0.50, 0, -1, ["upperBodyShortSleeve", "upperBodyLongSleeve", "upperBodyCasual", "upperBodyFormal", "upperBodyJacket", "upperBodyLogo", "upperBodyPlaid", "upperBodyThinStripes", "upperBodyTshirt", "upperBodyOther", "upperBodyVNeck", "upperBodyNoSleeve", "upperBodySuit", "upperBodySweater", "upperBodyThickStripes"]),
    _head("upper_body_color", 78, 0.35, 1, -1, [f"upperBody{c}" for c in COLORS]),
    _head("lower_body_style", 89, 0.50, 0, -1, ["lowerBodyShorts", "lowerBodyTrousers", "lowerBodyShortSkirt", "lowerBodyLongSkirt", "lowerBodyCasual", "lowerBodyFormal", "lowerBodyJeans", "lowerBodyCapri", "lowerBodyHotPants", "lowerBodyPlaid", "lowerBodyThinStripes", "lowerBodySuits"]),
    _head("lower_body_color", 101, 0.35, 1, -1, [f"lowerBody{c}" for c in COLORS]),
    _head("footwear_type", 112, 0.50, 0, -1, ["footwearShoes", "footwearLeatherShoes", "footwearSandals", "footwearSneaker", "footwearBoots", "footwearStocking"]),
    _head("footwear_color", 118, 0.50, 1, -1, [f"footwear{c}" for c in COLORS]),
    _head("viewpoint", 129, 0.50, 1, -1, ["viewpointFront", "viewpointBack", "viewpointSide"]),
)
ATTR_DIM = 132
ALL_LABELS: list[str] = [label for head in ATTR_HEADS for label in head.labels]
assert len(ALL_LABELS) == ATTR_DIM


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -80.0, 80.0)))


def postprocess_attr(probs: np.ndarray) -> np.ndarray:
    """Port of postprocess_attr() from cam_yolo_attr_web.c. Returns bool[132]."""
    sel = np.zeros(ATTR_DIM, dtype=bool)
    for head in ATTR_HEADS:
        p = probs[head.offset:head.offset + head.dim]
        s = sel[head.offset:head.offset + head.dim]
        if head.exclusive:
            best = int(np.argmax(p))
            if p[best] >= head.threshold:
                s[best] = True
            continue
        s[:] = p >= head.threshold
        if head.nothing_idx >= 0 and s[head.nothing_idx]:
            others = [i for i in range(head.dim) if i != head.nothing_idx and s[i]]
            if others:
                best_other = max(others, key=lambda i: p[i])
                if p[head.nothing_idx] >= p[best_other]:
                    s[[i for i in range(head.dim) if i != head.nothing_idx]] = False
                else:
                    s[head.nothing_idx] = False
    # Dependency / visibility suppression (same indices as the C code).
    if not sel[16:20].any():
        sel[20:31] = False          # no hat -> no hat colour
    if sel[8]:
        sel[89:129] = False         # upper half only -> no lower body / footwear
    if sel[9]:
        sel[10:38] = False          # lower half only -> no head accessories
        sel[49:89] = False
    if sel[130]:
        sel[15:38] = False          # back view -> hat/mask/glasses not visible
    return sel


def to_payload(selected: dict[str, float]) -> dict:
    """Build `attributes_by_head` + `positive_attributes` like /api/person in the C app.

    Extra cues (hood, face covered, weapons, ...) are reported under head "cues".
    """
    by_head: dict[str, dict] = {}
    positive: list[dict] = []
    for head in ATTR_HEADS:
        chosen = [{"label": l, "prob": round(selected[l], 5)} for l in head.labels if l in selected]
        by_head[head.name] = {"selected": chosen}
        positive += [{"head": head.name, **c} for c in chosen]
    known = set(ALL_LABELS)
    cues = [{"label": l, "prob": round(p, 5)} for l, p in selected.items() if l not in known]
    by_head["cues"] = {"selected": cues}
    positive += [{"head": "cues", **c} for c in cues]
    return {"attributes_by_head": by_head, "positive_attributes": positive}


def crop_with_pad(frame_bgr: np.ndarray, bbox, pad_ratio: float = 0.05) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    x0, y0, x1, y1 = bbox
    pad = pad_ratio * max(x1 - x0, y1 - y0)
    x0, y0 = max(0, int(x0 - pad)), max(0, int(y0 - pad))
    x1, y1 = min(w - 1, int(x1 + pad)), min(h - 1, int(y1 + pad))
    return frame_bgr[y0:y1, x0:x1]


# --------------------------------------------------------------------------- #
# Engine 1: trained ResNet18 via onnxruntime
# --------------------------------------------------------------------------- #
class OnnxAttrEngine:
    name = "resnet18-onnx"

    def __init__(self, onnx_path: Path, metadata_path: Path | None = None):
        import onnxruntime as ort

        meta = {}
        if metadata_path and metadata_path.is_file():
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        cfg = meta.get("input", {})
        self.width = int(cfg.get("width", 192))
        self.height = int(cfg.get("height", 256))
        self.mean = np.array(cfg.get("mean", [0.485, 0.456, 0.406]), dtype=np.float32).reshape(3, 1, 1)
        self.std = np.array(cfg.get("std", [0.229, 0.224, 0.225]), dtype=np.float32).reshape(3, 1, 1)
        labels = meta.get("output", {}).get("labels")
        if labels and list(labels) != ALL_LABELS:
            raise ValueError("model_68.onnx.json label order differs from ATTR_HEADS")
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
        self.sess = ort.InferenceSession(str(onnx_path), providers=providers)
        self.input_name = self.sess.get_inputs()[0].name

    def predict(self, frame_bgr: np.ndarray, bbox, head_box=None) -> np.ndarray:
        crop = crop_with_pad(frame_bgr, bbox)
        rgb = cv2.cvtColor(cv2.resize(crop, (self.width, self.height), interpolation=cv2.INTER_LINEAR), cv2.COLOR_BGR2RGB)
        chw = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))
        tensor = ((chw - self.mean) / self.std)[None].astype(np.float32)
        logits = self.sess.run(None, {self.input_name: tensor})[0].reshape(-1)
        return sigmoid(logits.astype(np.float32))


# --------------------------------------------------------------------------- #
# Engine 2: zero-shot CLIP fallback
# --------------------------------------------------------------------------- #
_COLOR_WORDS = {"Black": "black", "Grey": "grey", "White": "white", "Brown": "brown", "Red": "red", "Pink": "pink",
                "Yellow": "yellow", "Orange": "orange", "Green": "green", "Blue": "blue", "Purple": "purple"}

# label -> list of prompt variants (embeddings are averaged)
CLIP_PROMPTS: dict[str, list[str]] = {
    "personalLess15": ["a photo of a child", "a photo of a kid under 15 years old"],
    "personalLess30": ["a photo of a young adult in their twenties", "a photo of a young person"],
    "personalLess45": ["a photo of an adult in their thirties or early forties"],
    "personalLess60": ["a photo of a middle-aged person in their fifties"],
    "personalLarger60": ["a photo of an elderly person over 60", "a photo of an old person with grey hair"],
    "personalMale": ["a photo of a man", "a photo of a male person"],
    "personalFemale": ["a photo of a woman", "a photo of a female person"],
    "bodyFull": ["a full-body photo of a person from head to feet"],
    "bodyUpperHalf": ["a close-up photo of a person's head and upper body", "a webcam photo of a person from the chest up"],
    "bodyLowerHalf": ["a photo of only the legs and feet of a person"],
    "accessoryMuffler": ["a person wearing a scarf around the neck", "a person wearing a muffler covering the chin"],
    "accessoryNothing": ["a person with a bare neck and no headphones, no scarf"],
    "accessoryHeadphone": ["a person wearing headphones"],
    "accessoryHairBand": ["a person wearing a hair band"],
    "accessoryKerchief": ["a person wearing a headscarf covering the head", "a person wearing a bandana on the head"],
    "hatNone": ["a person with no hat, bare head with visible hair", "a person without any headwear"],
    "hatCap": ["a person wearing a baseball cap", "a person wearing a cap with a visor"],
    "hatBeanie": ["a person wearing a knitted beanie hat"],
    "hatHelmet": ["a person wearing a motorcycle helmet", "a person wearing a helmet"],
    "hatOthers": ["a person wearing a hat", "a person wearing a hood over the head"],
    "maskNone": ["a person with an uncovered face, mouth and nose visible", "a face without a face mask"],
    "maskSurgical": ["a person wearing a blue surgical face mask", "a person wearing a medical face mask"],
    "maskClothN95": ["a person wearing a black cloth face mask", "a person wearing an N95 respirator mask"],
    "glassesNone": ["a person not wearing glasses, eyes clearly visible"],
    "glassesEyeglasses": ["a person wearing clear prescription eyeglasses"],
    "glassesSunglasses": ["a person wearing dark sunglasses", "a person wearing black tinted sunglasses"],
    "glassesOthers": ["a person wearing goggles"],
    "carryingBackpack": ["a person wearing a backpack"],
    "carryingOther": ["a person carrying a handbag"],
    "carryingMessengerBag": ["a person with a messenger bag over the shoulder"],
    "carryingNothing": ["a person carrying nothing, empty hands"],
    "carryingPlasticBags": ["a person carrying plastic bags"],
    "carryingBabyBuggy": ["a person pushing a baby stroller"],
    "carryingShoppingTro": ["a person pushing a shopping trolley"],
    "carryingUmbrella": ["a person holding an umbrella"],
    "carryingFolder": ["a person holding a folder of documents"],
    "carryingLuggageCase": ["a person pulling a rolling luggage case"],
    "carryingSuitcase": ["a person carrying a suitcase", "a person carrying a briefcase"],
    "hairShort": ["a person with short hair"],
    "hairLong": ["a person with long hair"],
    "hairBald": ["a bald person"],
    "upperBodyShortSleeve": ["a person wearing a short-sleeved shirt"],
    "upperBodyLongSleeve": ["a person wearing a long-sleeved shirt"],
    "upperBodyCasual": ["a person in casual clothes"],
    "upperBodyFormal": ["a person wearing a formal shirt"],
    "upperBodyJacket": ["a person wearing a jacket", "a person wearing a zip-up coat"],
    "upperBodyLogo": ["a person wearing a shirt with a printed logo"],
    "upperBodyPlaid": ["a person wearing a plaid shirt"],
    "upperBodyThinStripes": ["a person wearing a thin striped shirt"],
    "upperBodyTshirt": ["a person wearing a t-shirt"],
    "upperBodyOther": ["a person wearing a top"],
    "upperBodyVNeck": ["a person wearing a v-neck shirt"],
    "upperBodyNoSleeve": ["a person wearing a sleeveless tank top"],
    "upperBodySuit": ["a person wearing a suit and tie"],
    "upperBodySweater": ["a person wearing a hoodie", "a person wearing a sweater"],
    "upperBodyThickStripes": ["a person wearing a shirt with thick stripes"],
    "lowerBodyShorts": ["a person wearing shorts"],
    "lowerBodyTrousers": ["a person wearing long trousers"],
    "lowerBodyShortSkirt": ["a person wearing a short skirt"],
    "lowerBodyLongSkirt": ["a person wearing a long skirt"],
    "lowerBodyCasual": ["a person wearing casual pants"],
    "lowerBodyFormal": ["a person wearing formal dress pants"],
    "lowerBodyJeans": ["a person wearing jeans"],
    "lowerBodyCapri": ["a person wearing capri pants"],
    "lowerBodyHotPants": ["a person wearing hot pants"],
    "lowerBodyPlaid": ["a person wearing plaid pants"],
    "lowerBodyThinStripes": ["a person wearing striped pants"],
    "lowerBodySuits": ["a person wearing suit trousers"],
    "footwearShoes": ["a person wearing shoes"],
    "footwearLeatherShoes": ["a person wearing leather shoes"],
    "footwearSandals": ["a person wearing sandals"],
    "footwearSneaker": ["a person wearing sneakers"],
    "footwearBoots": ["a person wearing boots"],
    "footwearStocking": ["a person wearing stockings"],
    "viewpointFront": ["a photo of a person facing the camera"],
    "viewpointBack": ["a photo of a person from behind, back view"],
    "viewpointSide": ["a photo of a person in side view profile"],
}
for _c, _w in _COLOR_WORDS.items():
    CLIP_PROMPTS[f"hat{_c}"] = [f"a person wearing a {_w} hat"]
    CLIP_PROMPTS[f"hair{_c}"] = [f"a person with {_w} hair"]
    CLIP_PROMPTS[f"upperBody{_c}"] = [f"a person wearing a {_w} top", f"a person in {_w} clothes"]
    CLIP_PROMPTS[f"lowerBody{_c}"] = [f"a person wearing {_w} pants"]
    CLIP_PROMPTS[f"footwear{_c}"] = [f"a person wearing {_w} shoes"]
assert set(CLIP_PROMPTS) == set(ALL_LABELS), set(ALL_LABELS) ^ set(CLIP_PROMPTS)

# Heads judged on a head+neck crop instead of the full person crop.
HEAD_REGION_HEADS = {"accessory", "hat_type", "hat_color", "mask_type", "glasses_type", "hair_style", "hair_color"}


def head_box_from_keypoints(kps: np.ndarray | None, bbox, min_conf: float = 0.4):
    """Head+neck box from COCO pose keypoints (0 nose, 1-2 eyes, 3-4 ears, 5-6 shoulders).

    Returns None when the face is not visible enough (caller falls back to a heuristic).
    """
    if kps is None or len(kps) < 7:
        return None
    face = kps[:5][kps[:5, 2] >= min_conf]
    if len(face) < 2:
        return None
    cx, cy = float(face[:, 0].mean()), float(face[:, 1].mean())
    shoulders = kps[5:7][kps[5:7, 2] >= min_conf]
    spread = float(np.ptp(face[:, 0])) if len(face) > 1 else 0.0
    size = max(spread * 2.2, 0.18 * (bbox[2] - bbox[0]))
    if len(shoulders) == 2:
        size = max(size, 0.8 * abs(float(shoulders[0, 0] - shoulders[1, 0])))
    # Extend upward for hats, downward to the neck for masks / scarves.
    return (cx - 0.75 * size, cy - 0.95 * size, cx + 0.75 * size, cy + 0.85 * size)


class ClipBackend:
    """One shared CLIP model for the attribute engine and the visual cue detector."""

    def __init__(self, model_id: str = "openai/clip-vit-base-patch32", device: str | None = None):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = CLIPModel.from_pretrained(model_id).to(self.device).eval()
        self.processor = CLIPProcessor.from_pretrained(model_id)
        self.logit_scale = float(self.model.logit_scale.exp().item())

    def text_embeddings(self, prompt_sets: list[list[str]]):
        """One averaged, normalised embedding per prompt set -> [N, D]."""
        torch = self.torch
        with torch.no_grad():
            out = []
            for prompts in prompt_sets:
                tok = self.processor(text=prompts, return_tensors="pt", padding=True).to(self.device)
                emb = self.model.get_text_features(**tok)
                emb = (emb / emb.norm(dim=-1, keepdim=True)).mean(dim=0)
                out.append(emb / emb.norm())
            return torch.stack(out)

    def image_embeddings(self, crops_bgr: list[np.ndarray]):
        rgbs = [cv2.cvtColor(c, cv2.COLOR_BGR2RGB) for c in crops_bgr]
        with self.torch.no_grad():
            px = self.processor(images=rgbs, return_tensors="pt").to(self.device)
            emb = self.model.get_image_features(**px)
            return emb / emb.norm(dim=-1, keepdim=True)


def person_crops(frame_bgr: np.ndarray, bbox, head_box=None) -> tuple[np.ndarray, np.ndarray]:
    """(body crop, head+neck crop)."""
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    body = crop_with_pad(frame_bgr, bbox)
    if head_box is None:
        # No face keypoints: tall box -> full body (head ~ top 22%), else close-up (top 40%).
        head_frac = 0.22 if bh > 2.0 * bw else 0.40
        head_box = (x0, y0, x1, y0 + head_frac * bh)
    head = crop_with_pad(frame_bgr, head_box, 0.0)
    return body, (head if head.size else body)


class ClipAttrEngine:
    name = "clip-zero-shot"

    def __init__(self, backend: ClipBackend):
        self.clip = backend
        self.text_emb = backend.text_embeddings([CLIP_PROMPTS[l] for l in ALL_LABELS])  # [132, D]

    def predict(self, frame_bgr: np.ndarray, bbox, head_box=None) -> np.ndarray:
        body, head = person_crops(frame_bgr, bbox, head_box)
        img_emb = self.clip.image_embeddings([body, head])
        sims = (self.clip.logit_scale * img_emb @ self.text_emb.T).cpu().numpy()  # [2, 132]
        probs = np.zeros(ATTR_DIM, dtype=np.float32)
        for head_def in ATTR_HEADS:
            row = 1 if head_def.name in HEAD_REGION_HEADS else 0
            logits = sims[row, head_def.offset:head_def.offset + head_def.dim]
            e = np.exp(logits - logits.max())
            probs[head_def.offset:head_def.offset + head_def.dim] = e / e.sum()
        return probs


# --------------------------------------------------------------------------- #
# Extra cues not covered by the 132-label model
# --------------------------------------------------------------------------- #
# label -> (positive prompts, negative prompts), judged on the head+neck crop
VISUAL_CUES: dict[str, tuple[list[str], list[str]]] = {
    "hoodUp": (["a person wearing a hoodie with the hood pulled up over the head",
                "a person with a hood covering the head"],
               ["a person with an uncovered head and visible hair",
                "a person wearing a hoodie with the hood down"]),
    "faceCovered": (["a person wearing a black balaclava ski mask covering the whole face",
                     "a face wrapped in a scarf so only the eyes are visible"],
                    ["a person with a clearly visible face",
                     "a person wearing a normal medical face mask with the eyes and forehead visible"]),
    "fullFaceHelmet": (["a person wearing a full-face motorcycle helmet with the visor down"],
                       ["a person not wearing a helmet", "a person wearing an open-face helmet, face visible"]),
    # Fallback for webcam close-ups where the wrists are below the frame and pose cannot see them
    "handsCoveringFace": (["a person covering their face with their hands", "hands pressed against the cheeks and face"],
                          ["a face with no hands near it", "a person with hands down, face fully visible"]),
}

# COCO class id -> label. Weapons become new labels; bags / umbrella reinforce the
# carrying head of the attribute model with a real detection.
COCO_OBJECTS = {
    43: "weaponKnife", 34: "weaponBat", 76: "weaponScissors",
    24: "carryingBackpack", 26: "carryingOther", 28: "carryingSuitcase", 25: "carryingUmbrella",
}
EXTRA_LABELS: list[str] = list(VISUAL_CUES) + ["weaponKnife", "weaponBat", "weaponScissors", "weaponGun", "wearingGloves"]
EXTRA_THRESHOLDS = {"hoodUp": 0.65, "faceCovered": 0.7, "fullFaceHelmet": 0.7, "handsCoveringFace": 0.7,
                    "weaponKnife": 0.35, "weaponBat": 0.35, "weaponScissors": 0.35,
                    "weaponGun": 0.6, "wearingGloves": 0.7}

# What a hand can hold. Benign classes are listed on purpose: a phone or a cup must win over
# "gun"/"knife" instead of being forced into a weapon class.
HAND_OBJECTS: dict[str, list[str]] = {
    "gun": ["a hand holding a gun", "a hand holding a black pistol"],
    "knife": ["a hand holding a knife", "a hand holding a sharp blade"],
    "phone": ["a hand holding a smartphone", "a hand holding a mobile phone"],
    "cup": ["a hand holding a cup or a bottle"],
    "small": ["a hand holding a pen, keys or a small object"],
    "empty": ["an empty open hand", "a hand with nothing in it"],
}
GLOVE_PROMPTS = (["a hand wearing a glove", "a hand in a black leather glove"],
                 ["a bare hand with visible skin and fingers"])


def face_box_from_keypoints(kps: np.ndarray | None, bbox, min_conf: float = 0.4):
    """Tight face box (forehead -> chin, no neck / collar) for mask & sunglasses checks."""
    if kps is None or len(kps) < 5:
        return None
    pts = [kps[i, :2] for i in range(5) if kps[i, 2] >= min_conf]
    eyes = [kps[i, :2] for i in (1, 2) if kps[i, 2] >= min_conf]
    ears = [kps[i, :2] for i in (3, 4) if kps[i, 2] >= min_conf]
    if len(pts) < 2:
        return None
    if len(ears) == 2:
        w = abs(float(ears[0][0] - ears[1][0])) * 1.15
    elif len(eyes) == 2:
        w = abs(float(eyes[0][0] - eyes[1][0])) * 2.6
    else:
        w = 0.25 * (bbox[2] - bbox[0])
    cx = float(np.mean([q[0] for q in pts]))
    ey = float(np.mean([q[1] for q in eyes])) if eyes else float(kps[0, 1])
    return (cx - w / 2, ey - 0.45 * w, cx + w / 2, ey + 0.85 * w)


# Binary checks on the tight face crop. Measured on webcam snapshots: mask 0.98 vs bare face 0.22,
# where the 3-way softmax on the head+neck crop gave 0.68-0.79 "cloth mask" for bare faces.
FACE_CHECKS: dict[str, tuple[list[str], list[str]]] = {
    "mask": (["a close-up photo of a face wearing a face mask that covers the mouth and nose",
              "a person wearing a surgical mask", "a person wearing a cloth face mask"],
             ["a close-up photo of a face with visible lips, mouth and chin",
              "a person with a bare face and no mask", "a selfie of a person without a mask"]),
    "sunglasses": (["a close-up photo of a face wearing dark sunglasses that hide the eyes",
                    "a person wearing black sunglasses"],
                   ["a close-up photo of a face with clearly visible eyes",
                    "a person wearing clear prescription glasses, eyes visible", "a person without sunglasses"]),
}


class FaceVerifier:
    """Recalibrates the mask / glasses heads of the zero-shot engine from a tight face crop."""

    def __init__(self, backend: ClipBackend):
        self.clip = backend
        self.pos = backend.text_embeddings([v[0] for v in FACE_CHECKS.values()])
        self.neg = backend.text_embeddings([v[1] for v in FACE_CHECKS.values()])

    def predict(self, face_crop: np.ndarray) -> dict[str, float]:
        img = self.clip.image_embeddings([face_crop])
        d = (self.clip.logit_scale * (img @ self.pos.T - img @ self.neg.T)).cpu().numpy()[0]
        return {name: float(1.0 / (1.0 + np.exp(-v))) for name, v in zip(FACE_CHECKS, d)}

    @staticmethod
    def apply(probs: np.ndarray, checks: dict[str, float]):
        """Rewrite the 132-label mask / glasses heads in place, keeping the sub-type split."""
        def split(labels, positive, p_pos, negative):
            idx = [ALL_LABELS.index(l) for l in labels]
            pos_idx = [ALL_LABELS.index(l) for l in positive]
            share = probs[pos_idx] / max(float(probs[pos_idx].sum()), 1e-6)
            probs[idx] = 0.0
            probs[pos_idx] = p_pos * share
            probs[ALL_LABELS.index(negative)] = 1.0 - p_pos
        if "mask" in checks:
            split(["maskNone", "maskSurgical", "maskClothN95"], ["maskSurgical", "maskClothN95"], checks["mask"], "maskNone")
        if "sunglasses" in checks:
            # sunglasses vs. (none / eyeglasses / others) - keep the non-sunglasses split
            sun = ALL_LABELS.index("glassesSunglasses")
            rest = [ALL_LABELS.index(l) for l in ("glassesNone", "glassesEyeglasses", "glassesOthers")]
            share = probs[rest] / max(float(probs[rest].sum()), 1e-6)
            probs[sun] = checks["sunglasses"]
            probs[rest] = (1.0 - checks["sunglasses"]) * share


def hand_boxes(kps: np.ndarray | None, bbox, min_conf: float = 0.4) -> list[tuple]:
    """Boxes around each visible hand, extended past the wrist along the forearm."""
    if kps is None or len(kps) < 11:
        return []
    bw = bbox[2] - bbox[0]
    boxes = []
    for wi, ei in ((9, 7), (10, 8)):
        if kps[wi, 2] < min_conf:
            continue
        w = kps[wi, :2]
        if kps[ei, 2] >= min_conf:
            d = w - kps[ei, :2]
            center, size = w + 0.35 * d, max(0.9 * float(np.linalg.norm(d)), 0.22 * bw)
        else:
            center, size = w, 0.25 * bw
        half = size / 2
        boxes.append((center[0] - half, center[1] - half, center[0] + half, center[1] + half))
    return boxes


class HandCueDetector:
    """CLIP on hand crops: weapon in hand (gun / knife vs benign objects) and gloves."""

    def __init__(self, backend: ClipBackend):
        self.clip = backend
        self.obj_emb = backend.text_embeddings(list(HAND_OBJECTS.values()))
        self.glove_emb = backend.text_embeddings(list(GLOVE_PROMPTS))
        self.gun_idx, self.knife_idx = list(HAND_OBJECTS).index("gun"), list(HAND_OBJECTS).index("knife")

    def predict(self, frame_bgr: np.ndarray, kps, bbox) -> dict[str, float]:
        crops = [c for c in (crop_with_pad(frame_bgr, b, 0.0) for b in hand_boxes(kps, bbox)) if min(c.shape[:2]) >= 32]
        if not crops:
            return {}
        img = self.clip.image_embeddings(crops)
        obj = (self.clip.logit_scale * img @ self.obj_emb.T).cpu().numpy()
        obj = np.exp(obj - obj.max(axis=1, keepdims=True))
        obj /= obj.sum(axis=1, keepdims=True)
        glv = (self.clip.logit_scale * img @ self.glove_emb.T).cpu().numpy()
        glove_p = 1.0 / (1.0 + np.exp(glv[:, 1] - glv[:, 0]))
        return {"weaponGun": float(obj[:, self.gun_idx].max()), "handKnife": float(obj[:, self.knife_idx].max()),
                "wearingGloves": float(glove_p.max())}


class VisualCueDetector:
    """Binary CLIP checks (cue vs. not-cue) on the head crop -> prob per cue."""

    def __init__(self, backend: ClipBackend):
        self.clip = backend
        sets = []
        for pos, neg in VISUAL_CUES.values():
            sets += [pos, neg]
        self.text_emb = backend.text_embeddings(sets)  # [2 * n_cues, D]

    def predict(self, head_crop: np.ndarray) -> dict[str, float]:
        img = self.clip.image_embeddings([head_crop])
        sims = (self.clip.logit_scale * img @ self.text_emb.T).cpu().numpy()[0]
        return {label: float(1.0 / (1.0 + np.exp(sims[2 * i + 1] - sims[2 * i])))
                for i, label in enumerate(VISUAL_CUES)}


class ObjectCueDetector:
    """YOLO (COCO) on the region around a person: real detections of weapons and bags."""

    def __init__(self, weights: str, conf: float = 0.25, imgsz: int = 480):
        from ultralytics import YOLO

        self.model = YOLO(weights)
        self.conf, self.imgsz = conf, imgsz

    def predict(self, frame_bgr: np.ndarray, bbox) -> dict[str, float]:
        h, w = frame_bgr.shape[:2]
        x0, y0, x1, y1 = bbox
        # Widen the box so objects held beside the body are included.
        px, py = 0.35 * (x1 - x0), 0.10 * (y1 - y0)
        X0, Y0 = int(max(0, x0 - px)), int(max(0, y0 - py))
        X1, Y1 = int(min(w, x1 + px)), int(min(h, y1 + py))
        region = frame_bgr[Y0:Y1, X0:X1]
        if region.size == 0:
            return {}
        res = self.model(region, classes=list(COCO_OBJECTS), conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        out: dict[str, float] = {}
        for cls, conf in zip(res.boxes.cls.cpu().numpy().astype(int), res.boxes.conf.cpu().numpy()):
            label = COCO_OBJECTS.get(int(cls))
            if label:
                out[label] = max(out.get(label, 0.0), float(conf))
        return out


MIN_CUE_HEAD_PX = 48


class AttributePipeline:
    """132 attributes + extra cues for one person -> probability vector over ALL_LABELS + EXTRA_LABELS."""

    def __init__(self, onnx_path: Path, metadata_path: Path, clip_model: str,
                 objects_weights: str | None, use_cues: bool = True):
        self.clip = None
        if onnx_path.is_file():
            self.attr = OnnxAttrEngine(onnx_path, metadata_path)
        else:
            self.clip = ClipBackend(clip_model)
            self.attr = ClipAttrEngine(self.clip)
        self.cues = self.hands = self.face = None
        if use_cues:
            self.clip = self.clip or ClipBackend(clip_model)
            self.cues = VisualCueDetector(self.clip)
            self.hands = HandCueDetector(self.clip)
        if isinstance(self.attr, ClipAttrEngine):
            self.face = FaceVerifier(self.clip)  # the trained ResNet18 does not need this
        self.objects = ObjectCueDetector(objects_weights) if objects_weights else None
        parts = ([self.attr.name] + (["face"] if self.face else []) + (["cues", "hands"] if self.cues else [])
                 + (["objects"] if self.objects else []))
        self.name = "+".join(parts)

    def predict(self, frame_bgr: np.ndarray, bbox, head_box=None, kps=None) -> np.ndarray:
        probs = np.zeros(ATTR_DIM + len(EXTRA_LABELS), dtype=np.float32)
        x = lambda label: ATTR_DIM + EXTRA_LABELS.index(label)  # noqa: E731
        probs[:ATTR_DIM] = self.attr.predict(frame_bgr, bbox, head_box)
        fb = face_box_from_keypoints(kps, bbox) if self.face else None
        if fb is not None:
            face = crop_with_pad(frame_bgr, fb, 0.0)
            if face.size and min(face.shape[:2]) >= MIN_CUE_HEAD_PX:
                FaceVerifier.apply(probs, self.face.predict(face))
        _, head = person_crops(frame_bgr, bbox, head_box)
        # Cues need a head big enough to see; tiny far-away heads give random answers.
        if self.cues and min(head.shape[:2]) >= MIN_CUE_HEAD_PX:
            for label, p in self.cues.predict(head).items():
                probs[ATTR_DIM + EXTRA_LABELS.index(label)] = p
        if self.objects:
            nothing = ALL_LABELS.index("carryingNothing")
            for label, p in self.objects.predict(frame_bgr, bbox).items():
                if label in EXTRA_LABELS:
                    probs[ATTR_DIM + EXTRA_LABELS.index(label)] = p
                else:  # detected bag: at least `p` for that label, weaken "carryingNothing"
                    i = ALL_LABELS.index(label)
                    probs[i] = max(probs[i], p)
                    probs[nothing] = min(probs[nothing], 1.0 - p)
        if self.hands:
            hand = self.hands.predict(frame_bgr, kps, bbox)
            probs[x("weaponGun")] = hand.get("weaponGun", 0.0)
            probs[x("wearingGloves")] = hand.get("wearingGloves", 0.0)
            # A knife seen only by CLIP counts if it is clearly the best hand class (fused with YOLO).
            if hand.get("handKnife", 0.0) >= 0.6:
                probs[x("weaponKnife")] = max(probs[x("weaponKnife")], 0.8 * hand["handKnife"])
        return probs


def select_labels(probs: np.ndarray) -> dict[str, float]:
    """Full probability vector -> {selected label: prob} (132 attributes + extra cues)."""
    sel = postprocess_attr(probs[:ATTR_DIM])
    out = {ALL_LABELS[i]: float(probs[i]) for i in range(ATTR_DIM) if sel[i]}
    back_view = bool(sel[130])
    p_no_mask = float(probs[ALL_LABELS.index("maskNone")])
    p_helmet = float(probs[ALL_LABELS.index("hatHelmet")])
    for j, label in enumerate(EXTRA_LABELS):
        p = float(probs[ATTR_DIM + j])
        if p < EXTRA_THRESHOLDS[label]:
            continue
        # Cross-checks with the attribute model to cut false positives:
        if label in ("faceCovered", "fullFaceHelmet", "handsCoveringFace") and back_view:
            continue                      # face not visible from behind
        if label == "faceCovered" and p_no_mask >= 0.5:
            continue                      # attribute model sees an uncovered mouth/nose
        if label == "fullFaceHelmet" and p_helmet < 0.3 and p_no_mask >= 0.5:
            continue                      # neither a helmet nor a covered face
        out[label] = p
    return out
