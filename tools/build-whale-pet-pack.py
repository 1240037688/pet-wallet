#!/usr/bin/env python3
r"""Build the whale pet pack for Hermes' built-in pet system (DR-15).

Produces ``assets/whale-pet-pack/``:

    pet.json         {id, displayName, description, spritesheetPath, createdBy}
    spritesheet.png  Codex format — 8 cols x 9 rows = 1536x1872, frame 192x208,
                     6 frames per state, row order (top→bottom):
                     idle, running-right, running-left, waving, jumping,
                     failed, waiting, running, review

Pure stdlib (zlib + struct for the PNG encoder — no PIL in the project venv).
Deterministic output: every frame is a pure function of (pose, frame index),
so regeneration is reproducible and diffable.

Usage:
    .venv/Scripts/python.exe tools/build-whale-pet-pack.py

Install (user-executed, AGENTS.md §0 — D:\hermes is read-only to us):
    copy assets/whale-pet-pack/  →  <HERMES_HOME>/pets/whale/
    then pick "whale" in the Hermes pet gallery (or set display.pet.slug).

Geometry/spec facts verified against local hermes-agent source:
    agent/pet/constants.py  (FRAME_W/H, FRAMES_PER_STATE, CODEX_STATE_ROWS)
    agent/pet/store.py      (pets_dir(), load_pet: pet.json keys)
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from pathlib import Path

# ── Codex pet sheet geometry (agent/pet/constants.py) ──────────────────────
FRAME_W, FRAME_H = 192, 208
COLS, ROWS = 8, 9
FRAMES_PER_STATE = 6
SHEET_W, SHEET_H = COLS * FRAME_W, ROWS * FRAME_H  # 1536 x 1872

STATE_ROWS = ["idle", "running-right", "running-left", "waving", "jumping", "failed", "waiting", "running", "review"]

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "whale-pet-pack"

# ── palette ────────────────────────────────────────────────────────────────
BODY = (104, 165, 221, 255)      # whale blue
BODY_DARK = (82, 138, 194, 255)  # shading
BELLY = (214, 234, 250, 255)     # light belly
FIN = (61, 127, 184, 255)        # fins/tail
OUTLINE = (13, 43, 69, 255)      # dark outline
EYE = (13, 43, 69, 255)
WHITE = (255, 255, 255, 255)
SPOUT = (158, 208, 242, 255)     # water spray
BLUSH = (255, 170, 170, 255)
ACCENT = (232, 161, 58, 255)     # waiting "?" / review dots


class Canvas:
    """Tiny RGBA rasterizer over a row-major bytearray."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.buf = bytearray(w * h * 4)

    def px(self, x: int, y: int, color) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            r, g, b, a = color
            if a == 255:
                i = (y * self.w + x) * 4
                self.buf[i:i + 4] = bytes((r, g, b, 255))
            elif a > 0:  # simple over-composite for the few AA-ish colors
                i = (y * self.w + x) * 4
                sr, sg, sb, sa = self.buf[i], self.buf[i + 1], self.buf[i + 2], self.buf[i + 3]
                na = a + sa * (255 - a) // 255
                if na:
                    self.buf[i] = (r * a + sr * sa * (255 - a) // 255) // na
                    self.buf[i + 1] = (g * a + sg * sa * (255 - a) // 255) // na
                    self.buf[i + 2] = (b * a + sb * sa * (255 - a) // 255) // na
                    self.buf[i + 3] = na

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, color) -> None:
        x0, x1 = int(cx - rx) - 1, int(cx + rx) + 2
        y0, y1 = int(cy - ry) - 1, int(cy + ry) + 2
        for y in range(max(0, y0), min(self.h, y1)):
            dy = (y + 0.5 - cy) / max(ry, 0.01)
            span = rx * math.sqrt(max(0.0, 1.0 - dy * dy))
            if span <= 0:
                continue
            for x in range(max(0, int(cx - span)), min(self.w, int(cx + span) + 1)):
                dx = (x + 0.5 - cx) / max(rx, 0.01)
                if dx * dx + dy * dy <= 1.0:
                    self.px(x, y, color)

    def poly(self, pts, color) -> None:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        for y in range(max(0, int(min(ys))), min(self.h, int(max(ys)) + 1)):
            node_x = []
            j = len(pts) - 1
            for i in range(len(pts)):
                yi, yj = pts[i][1], pts[j][1]
                if (yi <= y < yj) or (yj <= y < yi):
                    node_x.append(pts[i][0] + (y - yi) / (yj - yi) * (pts[j][0] - pts[i][0]))
                j = i
            node_x.sort()
            for k in range(0, len(node_x) - 1, 2):
                for x in range(max(0, int(node_x[k])), min(self.w, int(node_x[k + 1]) + 1)):
                    self.px(x, y, color)

    def line(self, x0, y0, x1, y1, color, thick: int = 2) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0), 1) * 2)
        for i in range(steps + 1):
            t = i / steps
            cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            self.ellipse(cx, cy, thick / 2, thick / 2, color)

    def to_png_bytes(self) -> bytes:
        raw = bytearray()
        stride = self.w * 4
        for y in range(self.h):
            raw.append(0)  # filter: None
            raw += self.buf[y * stride:(y + 1) * stride]

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)  # RGBA8
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b"")
        )


def _draw_whale(cv: Canvas, cx: float, cy: float, *, t: float, pose: str) -> None:
    """One whale, parameterised by animation phase t ∈ [0,1)."""
    bob = math.sin(t * 2 * math.pi)
    sway = math.sin(t * 2 * math.pi)
    kick = math.sin((t + 0.25) * 2 * math.pi)

    flip = pose in ("running-left",)
    dirx = -1.0 if flip else 1.0

    if pose == "running-right" or pose == "running" or pose == "running-left":
        cy += bob * 2
        cx += dirx * 4 * math.sin(t * 2 * math.pi)
        tilt = -6 * dirx
    elif pose == "jumping":
        cy -= 22 * math.sin(t * math.pi)
        tilt = -10 * dirx
    elif pose == "failed":
        tilt = 180  # belly-up: mirrored vertically below
    elif pose == "waving":
        tilt = -4 * dirx
    else:
        cy += bob * 2
        tilt = 0

    # tail fluke (behind body)
    tail_x = cx + dirx * 52
    tail_y = cy - 2
    fluke = 10 * kick * dirx
    cv.poly(
        [(cx + dirx * 34, cy - 4), (tail_x - dirx * 6, tail_y - 20 - fluke), (tail_x + dirx * 10, tail_y - fluke),
         (tail_x + dirx * 6, tail_y + 14 + fluke), (cx + dirx * 34, cy + 8)],
        FIN,
    )
    # body
    cv.ellipse(cx, cy, 40, 26, BODY)
    cv.ellipse(cx - dirx * 4, cy + 8, 26, 12, BELLY)  # belly patch
    cv.ellipse(cx + dirx * 10, cy - 12, 22, 10, BODY)  # head bulge
    # side fin
    fin_y = cy + 14
    cv.poly([(cx - dirx * 6, fin_y - 4), (cx - dirx * 14, fin_y + 12), (cx + dirx * 4, fin_y + 2)], FIN)
    # waving pose: raised pectoral fin
    if pose == "waving":
        wag = sway * 8
        cv.line(cx + dirx * 6, cy + 4, cx + dirx * 26, cy - 22 + wag, FIN, thick=7)
    # eye (+ blink on idle frame 4; X-eyes when failed)
    ex, ey = cx - dirx * 22, cy - 8
    if pose == "failed":
        cv.line(ex - 4, ey - 4, ex + 4, ey + 4, WHITE, thick=2)
        cv.line(ex - 4, ey + 4, ex + 4, ey - 4, WHITE, thick=2)
        cv.line(ex - 4, ey - 4, ex + 4, ey + 4, EYE, thick=1)
        cv.line(ex - 4, ey + 4, ex + 4, ey - 4, EYE, thick=1)
    elif pose == "idle" and int(t * FRAMES_PER_STATE) == 3:
        cv.line(ex - 4, ey, ex + 4, ey, EYE, thick=3)  # blink
    else:
        cv.ellipse(ex, ey, 4, 4.6, WHITE)
        cv.ellipse(ex + dirx, ey, 3, 3.4, EYE)
    # mouth
    m_y = cy + 6
    if pose == "failed":
        cv.line(ex - dirx * 8, m_y + 6, ex - dirx * 20, m_y + 2, OUTLINE, thick=2)
    else:
        cv.line(ex - dirx * 4, m_y + 2, ex - dirx * 16, m_y - 2, OUTLINE, thick=2)
    # blush
    cv.ellipse(ex + dirx * 10, ey + 8, 4, 2.4, BLUSH)
    # spout / bubbles / marks
    sx, sy = cx + dirx * 2, cy - 30
    if pose in ("idle", "waving"):
        cv.line(sx, sy + 6, sx - 2, sy - 6, SPOUT, thick=3)
        for k in range(3):
            bx = sx - 6 + k * 6
            cv.ellipse(bx, sy - 12 - k * 5, 3, 3, SPOUT)
    elif pose == "running" or pose == "running-right" or pose == "running-left":
        for k in range(3):
            bx = cx - dirx * (52 + k * 9)
            cv.ellipse(bx, cy - 6 + bob * 3, 3.2 - k * 0.6, 3.2 - k * 0.6, SPOUT)
    elif pose == "jumping":
        cv.line(sx, sy - 8, sx - 2, sy - 22, SPOUT, thick=3)
        for k in range(2):
            cv.ellipse(sx - 8 + k * 16, sy - 4, 3, 3, SPOUT)
    elif pose == "waiting":
        cv.line(sx + 14, sy - 10, sx + 14, sy - 2, ACCENT, thick=3)
        cv.ellipse(sx + 14, sy - 15, 4, 4, (0, 0, 0, 0))
        cv.ellipse(sx + 14, sy - 14, 3.4, 3.4, ACCENT)
        cv.ellipse(sx + 14, sy + 4, 2, 2, ACCENT)
    elif pose == "review":
        for k in range(3):
            cv.ellipse(cx - dirx * (10 + k * 12), cy - 34 - k * 6, 3 + k, 3 + k, BELLY)


def _frame(pose: str, index: int) -> Canvas:
    cv = Canvas(FRAME_W, FRAME_H)
    t = index / FRAMES_PER_STATE
    cx, cy = FRAME_W / 2, FRAME_H / 2 + 6
    if pose == "failed":
        # belly-up: draw flipped vertically around cy
        tmp = Canvas(FRAME_W, FRAME_H)
        _draw_whale_upright(tmp, cx, cy, t=t, pose="idle")
        for y in range(FRAME_H):
            for x in range(FRAME_W):
                si = ((FRAME_H - 1 - y) * FRAME_W + x) * 4
                di = (y * FRAME_W + x) * 4
                if tmp.buf[si + 3]:
                    cv.buf[di:di + 4] = tmp.buf[si:si + 4]
        cv.line(cx - 30, cy - 40, cx + 30, cy - 34, SPOUT, thick=3)  # sinking bubbles
        return cv
    _draw_whale_upright(cv, cx, cy, t=t, pose=pose)
    return cv


def _draw_whale_upright(cv: Canvas, cx: float, cy: float, *, t: float, pose: str) -> None:
    _draw_whale(cv, cx, cy, t=t, pose=pose)


def build_sheet() -> Canvas:
    sheet = Canvas(SHEET_W, SHEET_H)
    for row, pose in enumerate(STATE_ROWS):
        for col in range(FRAMES_PER_STATE):
            frame = _frame(pose, col)
            ox, oy = col * FRAME_W, row * FRAME_H
            for y in range(FRAME_H):
                si = y * FRAME_W * 4
                di = ((oy + y) * SHEET_W + ox) * 4
                sheet.buf[di:di + FRAME_W * 4] = frame.buf[si:si + FRAME_W * 4]
    return sheet


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet = build_sheet()
    png = sheet.to_png_bytes()
    (OUT_DIR / "spritesheet.png").write_bytes(png)
    (OUT_DIR / "pet.json").write_text(
        json.dumps(
            {
                "id": "whale",
                "displayName": "Butler Whale 鲸鱼管家",
                "description": "hermes-whale-widget host pet — the accounting butler. "
                "Pair it with the Whale Wallet butler pane (drag the pane next to your pet).",
                "spritesheetPath": "spritesheet.png",
                "createdBy": "hermes-whale-widget",
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    # self-check: header must announce exactly the Codex geometry
    w, h = struct.unpack(">II", png[16:24])
    assert (w, h) == (SHEET_W, SHEET_H), (w, h)
    print(f"OK assets/whale-pet-pack/spritesheet.png {w}x{h} ({len(png)} bytes) + pet.json")
    print(f"rows: {STATE_ROWS}; frames: {FRAMES_PER_STATE}/state; install → <HERMES_HOME>/pets/whale/")


if __name__ == "__main__":
    main()
