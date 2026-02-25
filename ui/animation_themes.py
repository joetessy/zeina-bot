"""
Swappable animation renderers for the FaceWidget.

Each renderer implements draw_idle/listening/processing/speaking using the
FaceWidget's canvas primitives and helper methods.
"""
import math
from kivy.graphics import Color, Ellipse, Line, Rectangle


class AnimationRenderer:
    """Base class for face animation renderers."""

    def draw_idle(self, w, lx, rx, ey, r, mx, my, sw):
        raise NotImplementedError

    def draw_listening(self, w, lx, rx, ey, r, mx, my, sw):
        raise NotImplementedError

    def draw_processing(self, w, lx, rx, ey, r, mx, my, sw):
        raise NotImplementedError

    def draw_speaking(self, w, lx, rx, ey, r, mx, my, sw):
        raise NotImplementedError


class BotRenderer(AnimationRenderer):
    """Default vector style animation (extracted from FaceWidget)."""

    # Gaze waypoints: (dx, dy) pairs the pupils drift between
    _GAZE_WAYPOINTS = [
        (0.0,   0.0),
        (0.18,  0.08),
        (0.05,  0.0),
        (-0.15, 0.12),
        (0.0,   0.05),
        (0.12, -0.06),
        (-0.08, 0.0),
        (-0.20, 0.05),
        (0.0,   0.10),
        (0.10, -0.03),
    ]
    _GAZE_HOLD = 4.5
    _GAZE_MOVE = 2.0

    def _get_gaze(self, t):
        wp = self._GAZE_WAYPOINTS
        n = len(wp)
        step_dur = self._GAZE_HOLD + self._GAZE_MOVE
        cycle_dur = step_dur * n
        phase = t % cycle_dur
        idx = int(phase / step_dur)
        within = phase - idx * step_dur
        cur = wp[idx % n]
        nxt = wp[(idx + 1) % n]
        if within < self._GAZE_HOLD:
            micro = 0.02 * math.sin(t * 0.8 + idx)
            return (cur[0] + micro, cur[1] + micro * 0.5)
        else:
            p = (within - self._GAZE_HOLD) / self._GAZE_MOVE
            s = p * p * (3 - 2 * p)
            return (cur[0] + (nxt[0] - cur[0]) * s,
                    cur[1] + (nxt[1] - cur[1]) * s)

    def _blink_curve(self, p):
        return 0.5 + 0.5 * math.cos(p * math.pi * 2)

    def _smoothstep(self, edge0, edge1, x):
        t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
        return t * t * (3 - 2 * t)

    def draw_idle(self, w, lx, rx, ey, r, mx, my, sw):
        t = w._time()
        breath = math.sin(t * 0.25 + 1.0) * 0.012
        br = r * (1 + breath)
        eye_bob = math.sin(t * 0.25 + 1.0) * r * 0.04
        sway_x = math.sin(t * 0.12 + 0.5) * r * 0.06
        pdx, pdy = self._get_gaze(t)

        eye_state = "open"
        sparkle = False
        blush = False
        blink_openness = 1.0

        blink1 = t % 8.0
        blink1_dur = 0.28
        blink1_center = 4.0
        blink1_lo = blink1_center - blink1_dur / 2
        blink1_hi = blink1_center + blink1_dur / 2
        if blink1_lo < blink1 < blink1_hi:
            p = (blink1 - blink1_lo) / blink1_dur
            eye_state = "_blink"
            blink_openness = self._blink_curve(p)

        blink2 = (t + 5.0) % 14.0
        blink2_dur = 0.28
        blink2_center = 7.0
        blink2_lo = blink2_center - blink2_dur / 2
        blink2_hi = blink2_center + blink2_dur / 2
        if blink2_lo < blink2 < blink2_hi and eye_state == "open":
            p = (blink2 - blink2_lo) / blink2_dur
            eye_state = "_blink"
            blink_openness = self._blink_curve(p)

        big_cycle = t % 60.0
        if 22.0 < big_cycle < 27.0:
            sparkle_blend = (self._smoothstep(22.0, 24.0, big_cycle)
                             * (1 - self._smoothstep(25.0, 27.0, big_cycle)))
            sparkle = sparkle_blend
            blush = True
            pdx *= (1 - sparkle_blend * 0.5)
            pdy *= (1 - sparkle_blend * 0.5)
        elif 27.0 < big_cycle < 31.0:
            blush = True
            if big_cycle < 27.3:
                close_p = self._smoothstep(27.0, 27.3, big_cycle)
                eye_state = "_blink"
                blink_openness = 1.0 - close_p
            elif big_cycle < 29.5:
                eye_state = "squint"
            elif big_cycle < 29.8:
                close_p = self._smoothstep(29.5, 29.8, big_cycle)
                eye_state = "_blink"
                blink_openness = close_p * 0.05
            else:
                open_p = self._smoothstep(29.8, 30.5, big_cycle)
                eye_state = "_blink"
                blink_openness = open_p
            blend = (self._smoothstep(27.0, 27.3, big_cycle)
                     * (1 - self._smoothstep(29.5, 30.5, big_cycle)))
            pdx *= (1 - blend)
            pdy *= (1 - blend)
        elif 45.0 < big_cycle < 48.0:
            blush = True

        if abs(pdx) > 0.22:
            blush = True

        eye_size_mod = 1.0 + 0.012 * math.sin(t * 0.15)

        ey_adj = ey + eye_bob
        lx_adj = lx + sway_x
        rx_adj = rx + sway_x
        mx_adj = mx + sway_x

        if eye_state == "_blink":
            w._draw_eye_partial(lx_adj, ey_adj, br * eye_size_mod, blink_openness)
            w._draw_eye_partial(rx_adj, ey_adj, br * eye_size_mod, blink_openness)
        elif eye_state == "squint":
            w._draw_eye_squint(lx_adj, ey_adj, br * eye_size_mod)
            w._draw_eye_squint(rx_adj, ey_adj, br * eye_size_mod)
        else:
            w._draw_eye_open(lx_adj, ey_adj, br * eye_size_mod, pdx, pdy, sparkle)
            w._draw_eye_open(rx_adj, ey_adj, br * eye_size_mod, pdx, pdy, sparkle)

        if blush:
            blush_alpha = 0.30
            if 22.0 < big_cycle < 31.0:
                blush_alpha = 0.38 * (self._smoothstep(22.0, 24.0, big_cycle)
                                      * (1 - self._smoothstep(29.5, 31.0, big_cycle)))
            w._draw_blush(lx_adj, ey_adj, r, blush_alpha)
            w._draw_blush(rx_adj, ey_adj, r, blush_alpha)

        my_adj = my + eye_bob * 0.6
        if sparkle or eye_state == "squint":
            target_w = 0.15
            target_d = 0.055
        elif eye_state == "_blink" and blink_openness < 0.15:
            target_w = 0.10
            target_d = 0.025
        else:
            target_w = 0.12
            target_d = 0.044
        target_d += math.sin(t * 0.15) * 0.0012
        lerp_speed = 0.10
        w._smile_w += (target_w - w._smile_w) * lerp_speed
        w._smile_d += (target_d - w._smile_d) * lerp_speed
        if w.show_mouth:
            w._draw_smile(mx_adj, my_adj, sw, w._smile_w, w._smile_d)

    def draw_listening(self, w, lx, rx, ey, r, mx, my, sw):
        t = w._time()
        tilt = math.sin(t * 0.6) * r * 0.15
        bob = math.sin(t * 1.2) * r * 0.04
        pulse = 1.0 + 0.06 * math.sin(t * 2.5)
        lr = r * 1.2 * pulse
        pdx = 0.08 * math.sin(t * 1.3 + 0.5)
        pdy = 0.06 * math.sin(t * 0.9)

        blink_openness = 1.0
        blink_cycle = t % 6.0
        if blink_cycle > 5.6:
            p = (blink_cycle - 5.6) / 0.4
            blink_openness = self._blink_curve(p)

        ey_adj = ey + bob
        lx_adj = lx + tilt
        rx_adj = rx + tilt
        mx_adj = mx + tilt

        if blink_openness < 0.95:
            w._draw_eye_partial(lx_adj, ey_adj, lr, blink_openness)
            w._draw_eye_partial(rx_adj, ey_adj, lr, blink_openness)
        else:
            w._draw_eye_open(lx_adj, ey_adj, lr, pdx, pdy)
            w._draw_eye_open(rx_adj, ey_adj, lr, pdx, pdy)

        mid_x = (lx_adj + rx_adj) / 2
        signal_y = ey_adj + lr * 1.2
        signal_pulse = 2 + int(math.sin(t * 2.0) > 0.3)
        w._draw_signal_lines(mid_x, signal_y, r, count=signal_pulse)

        mouth_r = 0.028 + 0.006 * math.sin(t * 2.5)
        my_adj = my + bob * 0.6
        if w.show_mouth:
            w._draw_mouth_o(mx_adj, my_adj, sw, mouth_r)

    def draw_processing(self, w, lx, rx, ey, r, mx, my, sw):
        t = w._time()
        lr = r * 1.08
        tilt = math.sin(t * 0.25) * r * 0.15
        bob = math.sin(t * 0.5) * r * 0.04

        ey_adj = ey + bob
        lx_adj = lx + tilt
        rx_adj = rx + tilt
        mx_adj = mx + tilt

        base_dx = 0.22
        base_dy = 0.28
        search_dx = 0.08 * math.sin(t * 0.18 + 1.0) + 0.05 * math.sin(t * 0.31)
        search_dy = 0.06 * math.sin(t * 0.14 + 2.0) + 0.03 * math.cos(t * 0.23)
        pdx = base_dx + search_dx
        pdy = base_dy + search_dy

        blink_openness = 1.0
        blink_cycle = t % 8.0
        if blink_cycle > 7.4:
            blink_p = (blink_cycle - 7.4) / 0.6
            blink_openness = self._blink_curve(blink_p)

        if blink_openness < 0.95:
            w._draw_eye_partial(lx_adj, ey_adj, lr, blink_openness)
            w._draw_eye_partial(rx_adj, ey_adj, lr, blink_openness)
        else:
            w._draw_eye_open(lx_adj, ey_adj, lr, pdx, pdy)
            w._draw_eye_open(rx_adj, ey_adj, lr, pdx, pdy)

        blush_alpha = 0.28 + 0.08 * math.sin(t * 0.5)
        w._draw_blush(lx_adj, ey_adj, r, blush_alpha)
        w._draw_blush(rx_adj, ey_adj, r, blush_alpha)

        my_adj = my + bob * 0.6
        mouth_drift = math.sin(t * 0.4) * sw * 0.012
        mouth_size = 0.016 + 0.003 * math.sin(t * 0.7)
        if w.show_mouth:
            w._draw_mouth_o(mx_adj + mouth_drift, my_adj, sw, mouth_size)

        thought_x = rx_adj + lr * 1.8
        thought_y = ey_adj + lr * 0.8
        w._draw_thought_dots(thought_x, thought_y, r, t)

    def draw_speaking(self, w, lx, rx, ey, r, mx, my, sw):
        t = w._time()
        bob = math.sin(t * 1.4) * r * 0.06
        sway = math.sin(t * 0.5 + 0.3) * r * 0.05

        ey_adj = ey + bob
        lx_adj = lx + sway
        rx_adj = rx + sway
        mx_adj = mx + sway

        lr = r * 1.15
        sparkle_raw = math.sin(t * 0.8 + 0.3)
        sparkle = max(0.0, sparkle_raw)
        sparkle = sparkle * sparkle
        blush_raw = math.sin(t * 0.8 + 0.3)
        blush_alpha = max(0.0, blush_raw) * 0.40

        pdx = 0.06 * math.sin(t * 0.8) + 0.03 * math.sin(t * 1.5)
        pdy = 0.03 * math.cos(t * 0.6)

        blink_openness = 1.0
        blink_cycle = t % 5.0
        if blink_cycle > 4.7:
            blink_p = (blink_cycle - 4.7) / 0.3
            blink_openness = self._blink_curve(blink_p)

        blink2_cycle = (t + 3.0) % 8.0
        if blink2_cycle > 7.7 and blink_openness > 0.95:
            blink_p2 = (blink2_cycle - 7.7) / 0.3
            blink_openness = self._blink_curve(blink_p2)

        if blink_openness < 0.95:
            w._draw_eye_partial(lx_adj, ey_adj, lr, blink_openness)
            w._draw_eye_partial(rx_adj, ey_adj, lr, blink_openness)
        else:
            w._draw_eye_open(lx_adj, ey_adj, lr, pdx, pdy, sparkle)
            w._draw_eye_open(rx_adj, ey_adj, lr, pdx, pdy, sparkle)

        if blush_alpha > 0.02:
            w._draw_blush(lx_adj, ey_adj, r, blush_alpha)
            w._draw_blush(rx_adj, ey_adj, r, blush_alpha)

        mh_frac = (
            0.014
            + 0.007 * math.sin(t * 14.0)
            + 0.005 * math.sin(t * 9.5 + 0.7)
            + 0.003 * math.sin(t * 19.0 + 1.3)
        )
        mh_frac = max(0.004, mh_frac)
        mw_frac = 0.03 + 0.007 * math.sin(t * 8.5 + 0.5)

        if w.show_mouth:
            Color(*w.MOUTH_COLOR)
            mw = sw * mw_frac
            mh = sw * mh_frac
            Ellipse(pos=(mx_adj - mw, my - mh), size=(mw * 2, mh * 2))


class ASCIIRenderer(AnimationRenderer):
    """ASCII art animation style — ports the terminal face.py animations to Kivy.

    Renders Unicode ASCII art frames as text labels centered on the face canvas.
    """

    # Frame definitions from zeina/face.py
    FRAMES = {
        "idle": [
            "◕   ◕\n  ω", "◕   ◕\n  ω", "◕   ◕\n  ω",
            "◑   ◑\n  ω", "◑   ◑\n  ω",
            "◕   ◕\n  ω", "◕   ◕\n  ω",
            "◡   ◡\n  ω", "─   ─\n  ω", "◡   ◡\n  ω",
            "◕   ◕\n  ω", "◕   ◕\n  ω", "◕   ◕\n  ω",
            "◐   ◐\n  ω", "◐   ◐\n  ω",
            "◕   ◕\n  υ", "◕   ◕\n  υ",
            "◡   ◡\n  υ", "─   ─\n  υ", "◡   ◡\n  ω",
            "◕   ◕\n  ω", "◕   ◕\n  ω",
            "✧   ✧\n  ω", "✧   ✧\n  ω", "✧   ✧\n  ω", "✧   ✧\n  ω",
            "◠   ◠\n  ω",
            "◕   ◕\n  ω", "◕   ◕\n  ω",
            "◓   ◓\n  ω", "◓   ◓\n  ω",
            "◕   ◕\n  ω", "◕   ◕\n  ω", "◕   ◕\n  ω",
            "─   ─\n  υ", "◕   ◕\n  ω",
        ],
        "listening": [
            "●   ●\n  ○", "●   ●\n  ○",
            "◉   ◉\n  ○", "●   ●\n  ◎",
            "◉   ◉\n  ○", "●   ●\n  ○",
        ],
        "processing": [
            "◔   ◔\n  ~", "◑   ◑\n  ~",
            "◕   ◕\n  ~", "◐   ◐\n  ~",
            "◓   ◓\n  ~", "◕   ◕\n  ~",
            "◔   ◔\n  ~",
        ],
        "speaking": [
            "◕   ◕\n  ◡", "◕   ◕\n  ○",
            "◕   ◕\n  ◠", "◕   ◕\n  o",
            "✧   ✧\n  ○", "✧   ✧\n  ○", "✧   ✧\n  ○", "✧   ✧\n  ○",
            "◕   ◕\n  ◡", "◕   ◕\n  ○", "◕   ◕\n  ◠",
            "◕   ◕\n  ◡",
        ],
    }

    FRAME_DELAYS = {
        "idle": 0.55,
        "listening": 0.25,
        "processing": 0.18,
        "speaking": 0.14,
    }

    def __init__(self):
        super().__init__()
        self._frame_index = 0
        self._last_state = None
        self._frame_timer = 0.0
        # Find a font that can render Unicode geometric shapes
        from ui.icons import find_unicode_font
        self._font_path = find_unicode_font()

    def _get_frame(self, state, dt):
        """Advance frame based on per-state delay, return current ASCII text."""
        if state != self._last_state:
            self._last_state = state
            self._frame_index = 0
            self._frame_timer = 0.0

        frames = self.FRAMES.get(state, self.FRAMES["idle"])
        delay = self.FRAME_DELAYS.get(state, 0.3)

        self._frame_timer += dt
        if self._frame_timer >= delay:
            self._frame_timer -= delay
            self._frame_index = (self._frame_index + 1) % len(frames)

        return frames[self._frame_index % len(frames)]

    def _render_text(self, w, lx, rx, ey, r, mx, my, sw, state):
        """Render ASCII frame as Kivy text on the canvas."""
        from kivy.graphics import Color as GColor, Rectangle as GRect
        from kivy.core.text import Label as CoreLabel

        dt = w.FRAME_DELAY
        text = self._get_frame(state, dt)
        if not w.show_mouth:
            text = text.split('\n')[0]

        # Use face colors for the text
        color = w.EYE_COLOR

        # Scale font size relative to face area — larger for better visibility
        font_size = int(min(sw, (ey - my + r * 2)) * 0.62)
        font_size = max(60, min(font_size, 220))

        kwargs = dict(
            text=text,
            font_size=font_size,
            color=color,
            halign='center',
            valign='middle',
        )
        if self._font_path:
            kwargs['font_name'] = self._font_path
        label = CoreLabel(**kwargs)
        label.refresh()
        tex = label.texture
        if tex:
            tw, th = tex.size
            cx = mx - tw / 2
            cy = (ey + my) / 2 - th / 2
            GColor(1, 1, 1, 1)
            GRect(pos=(cx, cy), size=tex.size, texture=tex)

    def draw_idle(self, w, lx, rx, ey, r, mx, my, sw):
        self._render_text(w, lx, rx, ey, r, mx, my, sw, "idle")

    def draw_listening(self, w, lx, rx, ey, r, mx, my, sw):
        self._render_text(w, lx, rx, ey, r, mx, my, sw, "listening")

    def draw_processing(self, w, lx, rx, ey, r, mx, my, sw):
        self._render_text(w, lx, rx, ey, r, mx, my, sw, "processing")

    def draw_speaking(self, w, lx, rx, ey, r, mx, my, sw):
        self._render_text(w, lx, rx, ey, r, mx, my, sw, "speaking")


ANIMATION_THEMES = {
    "vector": BotRenderer,
    "ascii": ASCIIRenderer,
}


def get_renderer(name: str) -> AnimationRenderer:
    """Get an animation renderer instance by name."""
    # Accept legacy "vecto key for backward compatibility
    cls = ANIMATION_THEMES.get(name) or ANIMATION_THEMES.get("vector")
    return cls()
