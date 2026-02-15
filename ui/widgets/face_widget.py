"""
BMO-style animated face widget for Zeina AI Assistant.

Canvas-drawn face with expressive eyes (pupils + highlights),
4 animation states with smooth procedural animation:
  idle (breathing, smooth glances, blinks, sparkles),
  listening (attentive, gentle tilt, pulsing),
  processing (cute anime thinking — eyes up, head tilt, thought dots),
  speaking (anime-style mouth, happy squints, head bob)
"""
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, RoundedRectangle, Rectangle, Line
from kivy.clock import Clock
from kivy.properties import StringProperty, NumericProperty
import math


class FaceWidget(Widget):
    """Canvas-drawn BMO-style face with state-responsive animations."""

    state = StringProperty("idle")
    frame = NumericProperty(0)

    # Frame rate: 24fps for all states (smooth)
    FRAME_DELAY = 0.042

    # Colors
    SCREEN_COLOR = (0.06, 0.12, 0.14, 1)
    EYE_COLOR = (0.85, 0.95, 0.90, 1)
    MOUTH_COLOR = (0.85, 0.95, 0.90, 1)
    PUPIL_COLOR = (0.06, 0.12, 0.14, 1)
    SPARKLE_COLOR = (0.6, 1.0, 0.9, 1.0)
    BLUSH_COLOR = (0.85, 0.45, 0.55, 0.35)
    BROW_COLOR = (0.75, 0.88, 0.82, 1)
    SIGNAL_COLOR = (0.3, 0.9, 0.75, 0.6)
    MOUTH_INNER_COLOR = (0.10, 0.06, 0.08, 1)
    LIP_COLOR = (0.78, 0.88, 0.84, 1)
    TONGUE_COLOR = (0.82, 0.48, 0.52, 0.55)
    THOUGHT_DOT_COLOR = (0.55, 0.85, 0.75, 0.7)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._anim_event = None
        self._global_tick = 0
        # Smoothed mouth parameters for idle (avoids jarring size jumps)
        self._smile_w = 0.12
        self._smile_d = 0.044
        self.bind(size=self._redraw, pos=self._redraw)
        Clock.schedule_once(self._start_animation, 0)

    def _start_animation(self, dt=None):
        self._anim_event = Clock.schedule_interval(self._tick, self.FRAME_DELAY)

    def _tick(self, dt):
        self._global_tick += 1
        self._redraw()

    def set_state(self, new_state):
        if new_state == self.state:
            return
        self.state = new_state
        self._redraw()

    # ── Helpers ──────────────────────────────────────────────────

    def _smoothstep(self, edge0, edge1, x):
        """Hermite smoothstep for smooth transitions."""
        t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
        return t * t * (3 - 2 * t)

    def _time(self):
        """Current animation time in seconds."""
        return self._global_tick * self.FRAME_DELAY

    # ── Main draw ───────────────────────────────────────────────

    def _redraw(self, *args):
        self.canvas.clear()

        w, h = self.size
        x, y = self.pos

        margin = min(w, h) * 0.06
        box_w = w - margin * 2
        box_h = h - margin * 2
        box_x = x + margin
        box_y = y + margin
        corner_r = min(box_w, box_h) * 0.08

        with self.canvas:
            Color(*self.SCREEN_COLOR)
            RoundedRectangle(
                pos=(box_x, box_y), size=(box_w, box_h),
                radius=[corner_r],
            )
            self._draw_face(box_x, box_y, box_w, box_h)

    def _draw_face(self, sx, sy, sw, sh):
        scale_dim = min(sw, sh)
        eye_y = sy + sh * 0.65
        eye_spacing = scale_dim * 0.28
        r = scale_dim * 0.08
        if eye_spacing < r * 3:
            eye_spacing = r * 3
        lx = sx + sw / 2 - eye_spacing / 2
        rx = sx + sw / 2 + eye_spacing / 2
        mx = sx + sw / 2
        my = sy + sh * 0.35

        state = self.state
        if state == "idle":
            self._draw_idle(lx, rx, eye_y, r, mx, my, sw)
        elif state == "listening":
            self._draw_listening(lx, rx, eye_y, r, mx, my, sw)
        elif state == "processing":
            self._draw_processing(lx, rx, eye_y, r, mx, my, sw)
        elif state == "speaking":
            self._draw_speaking(lx, rx, eye_y, r, mx, my, sw)

    # ── Eye primitives ──────────────────────────────────────────

    def _draw_eye_open(self, cx, cy, r, pupil_dx=0, pupil_dy=0, sparkle=0.0):
        """Draw an open eye. sparkle: 0.0 (off) to 1.0 (full sparkle)."""
        Color(*self.EYE_COLOR)
        Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2))
        # Pupil
        pr = r * 0.45
        Color(*self.PUPIL_COLOR)
        Ellipse(
            pos=(cx + pupil_dx * r - pr, cy + pupil_dy * r - pr),
            size=(pr * 2, pr * 2),
        )
        # Highlight — grows with sparkle blend
        hr = r * (0.22 + 0.10 * sparkle)
        Color(1, 1, 1, 0.9)
        Ellipse(
            pos=(cx - r * 0.28 - hr, cy + r * 0.28 - hr),
            size=(hr * 2, hr * 2),
        )
        if sparkle > 0.05:
            sr = r * 0.14 * sparkle
            Color(self.SPARKLE_COLOR[0], self.SPARKLE_COLOR[1],
                  self.SPARKLE_COLOR[2], sparkle)
            Ellipse(
                pos=(cx + r * 0.3 - sr, cy - r * 0.2 - sr),
                size=(sr * 2, sr * 2),
            )

    def _draw_eye_partial(self, cx, cy, r, openness):
        """Smoothly animatable eye between closed (0) and open (1).
        Draws a squished ellipse whose height scales with openness."""
        Color(*self.EYE_COLOR)
        if openness <= 0.05:
            # Fully closed - small thin line
            hw = r * 0.7
            Line(points=[cx - hw, cy, cx + hw, cy], width=1.6)
        else:
            h = r * 2 * max(0.08, openness)
            Ellipse(pos=(cx - r, cy - h / 2), size=(r * 2, h))
            if openness > 0.6:
                # Draw pupil when sufficiently open
                pr = r * 0.45 * openness
                Color(*self.PUPIL_COLOR)
                Ellipse(pos=(cx - pr, cy - pr), size=(pr * 2, pr * 2))
                # Highlight
                hr = r * 0.2 * openness
                Color(1, 1, 1, 0.8 * openness)
                Ellipse(
                    pos=(cx - r * 0.28 - hr, cy + r * 0.28 - hr),
                    size=(hr * 2, hr * 2),
                )

    def _draw_eye_squint(self, cx, cy, r):
        """Happy squint ^_^ arc."""
        Color(*self.EYE_COLOR)
        pts = []
        for i in range(24):
            t = i / 23.0
            px = cx - r + t * r * 2
            py = cy + math.sin(t * math.pi) * (r * 0.6)
            pts.extend([px, py])
        Line(points=pts, width=2.2)

    # ── Mouth primitives ────────────────────────────────────────

    def _draw_smile(self, cx, y, sw, width_frac=0.12, depth_frac=0.045):
        Color(*self.MOUTH_COLOR)
        mw = sw * width_frac
        pts = []
        for i in range(28):
            t = i / 27.0
            px = cx - mw + t * mw * 2
            py = y - math.sin(t * math.pi) * (sw * depth_frac)
            pts.extend([px, py])
        Line(points=pts, width=1.8)

    def _draw_mouth_o(self, cx, y, sw, radius_frac=0.03):
        Color(*self.MOUTH_COLOR)
        mr = sw * radius_frac
        Ellipse(pos=(cx - mr, y - mr), size=(mr * 2, mr * 2))

    def _draw_mouth_wave(self, cx, y, sw, phase=0, amplitude=0.015):
        Color(*self.MOUTH_COLOR)
        mw = sw * 0.1
        pts = []
        for i in range(24):
            t = i / 23.0
            px = cx - mw + t * mw * 2
            py = y + math.sin(t * math.pi * 2 + phase) * (sw * amplitude)
            pts.extend([px, py])
        Line(points=pts, width=1.5)

    def _draw_mouth_cat(self, cx, y, sw, width_frac=0.08):
        """Cute cat-mouth / 'w' shape — two little arcs meeting at center."""
        Color(*self.MOUTH_COLOR)
        mw = sw * width_frac
        pts = []
        for i in range(28):
            t = i / 27.0
            px = cx - mw + t * mw * 2
            # Two bumps meeting at center — cat mouth shape
            py = y - abs(math.sin(t * math.pi * 2)) * (sw * 0.018)
            pts.extend([px, py])
        Line(points=pts, width=1.8)

    def _draw_mouth_pout(self, cx, y, sw, width_frac=0.05):
        """Small round pout — tiny circle mouth."""
        Color(*self.MOUTH_COLOR)
        mr = sw * width_frac
        # Slight oval, taller than wide
        Ellipse(pos=(cx - mr * 0.7, y - mr), size=(mr * 1.4, mr * 2))

    # ── Accent primitives ───────────────────────────────────────

    def _draw_eyebrow(self, cx, cy, r, angle=0, width_frac=0.8):
        Color(*self.BROW_COLOR)
        bw = r * width_frac
        dy = r * 0.15 * angle
        pts = [cx - bw, cy + r * 1.4 + dy, cx + bw, cy + r * 1.4 - dy]
        Line(points=pts, width=1.6)

    def _draw_eyebrow_curved(self, cx, cy, r, furrow=0.0, is_left=True):
        """Curved anime-style eyebrow for thinking.
        furrow: 0 = relaxed, 1 = fully furrowed (inner end dips down)."""
        Color(*self.BROW_COLOR)
        bw = r * 0.85
        brow_y = cy + r * 1.45
        pts = []
        for i in range(16):
            t = i / 15.0
            px = cx - bw + t * bw * 2
            arch = math.sin(t * math.pi) * r * 0.18
            if is_left:
                inner_pull = -furrow * r * 0.25 * (1 - t) ** 2
            else:
                inner_pull = -furrow * r * 0.25 * t ** 2
            py = brow_y + arch + inner_pull
            pts.extend([px, py])
        Line(points=pts, width=2.0)

    def _draw_blush(self, cx, cy, r, alpha=0.35):
        Color(self.BLUSH_COLOR[0], self.BLUSH_COLOR[1],
              self.BLUSH_COLOR[2], alpha)
        br = r * 0.35
        Ellipse(pos=(cx - br, cy - r * 0.9 - br), size=(br * 2, br))

    def _draw_signal_lines(self, cx, cy, r, count=3):
        for i in range(count):
            Color(self.SIGNAL_COLOR[0], self.SIGNAL_COLOR[1],
                  self.SIGNAL_COLOR[2], self.SIGNAL_COLOR[3] * (1 - i * 0.25))
            arc_r = r * (1.2 + i * 0.7)
            pts = []
            for j in range(16):
                t = j / 15.0
                a = (math.pi * 0.3) + t * (math.pi * 0.4)
                px = cx + math.cos(a) * arc_r
                py = cy + math.sin(a) * arc_r
                pts.extend([px, py])
            Line(points=pts, width=1.3)

    def _draw_thought_dots(self, cx, cy, r, t):
        """Floating thought dots that drift upward — anime thinking indicator."""
        for i in range(3):
            phase = t * 0.7 + i * 2.2
            # Each dot floats up in a loop
            loop_pos = (phase % 4.5) / 4.5
            if loop_pos > 1.0:
                continue
            # Ease in-out for vertical drift
            drift_y = loop_pos * r * 3.5
            # Gentle horizontal wobble
            drift_x = math.sin(loop_pos * math.pi * 2 + i) * r * 0.6
            # Fade in then out
            alpha = math.sin(loop_pos * math.pi) * 0.7
            if alpha < 0.05:
                continue
            dot_r = r * (0.12 - i * 0.025)
            Color(self.THOUGHT_DOT_COLOR[0], self.THOUGHT_DOT_COLOR[1],
                  self.THOUGHT_DOT_COLOR[2], alpha)
            Ellipse(
                pos=(cx + drift_x - dot_r, cy + drift_y - dot_r),
                size=(dot_r * 2, dot_r * 2),
            )

    # ── State renderers ─────────────────────────────────────────

    # Gaze waypoints: (dx, dy) pairs the pupils drift between.
    # Each one is a spot the eyes "look at" for a while before moving on.
    _GAZE_WAYPOINTS = [
        (0.0,   0.0),    # center
        (0.18,  0.08),   # soft right
        (0.05,  0.0),    # almost center
        (-0.15, 0.12),   # up-left
        (0.0,   0.05),   # center-ish
        (0.12, -0.06),   # down-right glance
        (-0.08, 0.0),    # soft left
        (-0.20, 0.05),   # left
        (0.0,   0.10),   # up-center
        (0.10, -0.03),   # slight right
    ]
    # Seconds spent at each waypoint (hold) + seconds to drift to next (move)
    _GAZE_HOLD = 4.5
    _GAZE_MOVE = 2.0

    def _get_gaze(self, t):
        """Smoothly interpolate between gaze waypoints."""
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
            # Holding at current waypoint — tiny organic drift
            micro = 0.02 * math.sin(t * 0.8 + idx)
            return (cur[0] + micro, cur[1] + micro * 0.5)
        else:
            # Drifting to next waypoint
            p = (within - self._GAZE_HOLD) / self._GAZE_MOVE
            # Smoothstep for natural ease-in-out
            s = p * p * (3 - 2 * p)
            return (cur[0] + (nxt[0] - cur[0]) * s,
                    cur[1] + (nxt[1] - cur[1]) * s)

    def _draw_idle(self, lx, rx, ey, r, mx, my, sw):
        """Idle: slow breathing, eyes looking around naturally between waypoints,
        occasional blinks, rare sparkle/squint moments."""
        t = self._time()

        # ── Breathing ──
        breath = math.sin(t * 0.25 + 1.0) * 0.012
        br = r * (1 + breath)
        eye_bob = math.sin(t * 0.25 + 1.0) * r * 0.04
        sway_x = math.sin(t * 0.12 + 0.5) * r * 0.06

        # ── Gaze (waypoint-based looking around) ──
        pdx, pdy = self._get_gaze(t)

        # ── Blink system ──
        eye_state = "open"
        sparkle = False
        blush = False
        blink_openness = 1.0

        # Primary blink every ~8s (centered at 4s into cycle so it never wraps)
        blink1 = t % 8.0
        blink1_dur = 0.28
        blink1_center = 4.0
        blink1_lo = blink1_center - blink1_dur / 2
        blink1_hi = blink1_center + blink1_dur / 2
        if blink1_lo < blink1 < blink1_hi:
            p = (blink1 - blink1_lo) / blink1_dur
            eye_state = "_blink"
            blink_openness = self._blink_curve(p)

        # Secondary blink every ~14s, offset (centered at 7s)
        blink2 = (t + 5.0) % 14.0
        blink2_dur = 0.28
        blink2_center = 7.0
        blink2_lo = blink2_center - blink2_dur / 2
        blink2_hi = blink2_center + blink2_dur / 2
        if blink2_lo < blink2 < blink2_hi and eye_state == "open":
            p = (blink2 - blink2_lo) / blink2_dur
            eye_state = "_blink"
            blink_openness = self._blink_curve(p)

        # ── Sparkle / squint cycle (every ~60s) ──
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
            # Phase 1: blink closed then into squint (27.0-27.3s)
            # Phase 2: hold squint (27.3-29.5s)
            # Phase 3: squint to blink closed then reopen (29.5-30.5s)
            if big_cycle < 27.3:
                # Close eyes before squint
                close_p = self._smoothstep(27.0, 27.3, big_cycle)
                eye_state = "_blink"
                blink_openness = 1.0 - close_p
            elif big_cycle < 29.5:
                # Hold squint
                eye_state = "squint"
            elif big_cycle < 29.8:
                # Squint back to closed
                close_p = self._smoothstep(29.5, 29.8, big_cycle)
                eye_state = "_blink"
                blink_openness = close_p * 0.05  # stay near closed
            else:
                # Reopen eyes smoothly
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

        # ── Eye size variation ──
        eye_size_mod = 1.0 + 0.012 * math.sin(t * 0.15)

        # ── Draw ──
        ey_adj = ey + eye_bob
        lx_adj = lx + sway_x
        rx_adj = rx + sway_x
        mx_adj = mx + sway_x

        if eye_state == "_blink":
            self._draw_eye_partial(lx_adj, ey_adj, br * eye_size_mod, blink_openness)
            self._draw_eye_partial(rx_adj, ey_adj, br * eye_size_mod, blink_openness)
        elif eye_state == "squint":
            self._draw_eye_squint(lx_adj, ey_adj, br * eye_size_mod)
            self._draw_eye_squint(rx_adj, ey_adj, br * eye_size_mod)
        else:
            self._draw_eye_open(lx_adj, ey_adj, br * eye_size_mod, pdx, pdy, sparkle)
            self._draw_eye_open(rx_adj, ey_adj, br * eye_size_mod, pdx, pdy, sparkle)

        # ── Blush ──
        if blush:
            blush_alpha = 0.30
            if 22.0 < big_cycle < 31.0:
                blush_alpha = 0.38 * (self._smoothstep(22.0, 24.0, big_cycle)
                                      * (1 - self._smoothstep(29.5, 31.0, big_cycle)))
            self._draw_blush(lx_adj, ey_adj, r, blush_alpha)
            self._draw_blush(rx_adj, ey_adj, r, blush_alpha)

        # ── Mouth ──
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
        self._smile_w += (target_w - self._smile_w) * lerp_speed
        self._smile_d += (target_d - self._smile_d) * lerp_speed
        self._draw_smile(mx_adj, my_adj, sw, self._smile_w, self._smile_d)

    def _blink_curve(self, p):
        """Map blink progress (0..1) to eye openness (1 -> 0 -> 1).
        Uses smooth cosine for natural easing."""
        return 0.5 + 0.5 * math.cos(p * math.pi * 2)

    # ── Listening ──

    def _draw_listening(self, lx, rx, ey, r, mx, my, sw):
        """Attentive listening: wide focused eyes, gentle head tilt,
        soft pulsing, subtle pupil tracking."""
        t = self._time()

        # Gentle tilt toward speaker (slight lean)
        tilt = math.sin(t * 0.6) * r * 0.15
        bob = math.sin(t * 1.2) * r * 0.04

        # Eyes slightly wider when listening
        pulse = 1.0 + 0.06 * math.sin(t * 2.5)
        lr = r * 1.2 * pulse

        # Subtle pupil tracking — small attentive movements
        pdx = 0.08 * math.sin(t * 1.3 + 0.5)
        pdy = 0.06 * math.sin(t * 0.9)

        # Occasional attentive blink (every ~6s)
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
            self._draw_eye_partial(lx_adj, ey_adj, lr, blink_openness)
            self._draw_eye_partial(rx_adj, ey_adj, lr, blink_openness)
        else:
            self._draw_eye_open(lx_adj, ey_adj, lr, pdx, pdy)
            self._draw_eye_open(rx_adj, ey_adj, lr, pdx, pdy)

        # Signal lines above
        mid_x = (lx_adj + rx_adj) / 2
        signal_y = ey_adj + lr * 1.2
        signal_pulse = 2 + int(math.sin(t * 2.0) > 0.3)
        self._draw_signal_lines(mid_x, signal_y, r, count=signal_pulse)

        # Soft "o" mouth that gently breathes
        mouth_r = 0.028 + 0.006 * math.sin(t * 2.5)
        my_adj = my + bob * 0.6
        self._draw_mouth_o(mx_adj, my_adj, sw, mouth_r)

    # ── Processing ──

    def _draw_processing(self, lx, rx, ey, r, mx, my, sw):
        """Cute anime thinking: eyes locked upper-right searching for an answer,
        slow gentle blinks, small mouth drifting side-to-side, thought dots."""
        t = self._time()
        lr = r * 1.08

        # Head tilt — slow rock
        tilt = math.sin(t * 0.25) * r * 0.15
        bob = math.sin(t * 0.5) * r * 0.04

        ey_adj = ey + bob
        lx_adj = lx + tilt
        rx_adj = rx + tilt
        mx_adj = mx + tilt

        # ── Eyes: locked upper-right with slow searching drift ──
        # Base gaze: up and to the right
        base_dx = 0.22
        base_dy = 0.28
        # Slow searching drift layered on top
        search_dx = 0.08 * math.sin(t * 0.18 + 1.0) + 0.05 * math.sin(t * 0.31)
        search_dy = 0.06 * math.sin(t * 0.14 + 2.0) + 0.03 * math.cos(t * 0.23)
        pdx = base_dx + search_dx
        pdy = base_dy + search_dy

        # Occasional slow blink (every ~8s)
        blink_openness = 1.0
        blink_cycle = t % 8.0
        if blink_cycle > 7.4:
            blink_p = (blink_cycle - 7.4) / 0.6
            blink_openness = self._blink_curve(blink_p)

        if blink_openness < 0.95:
            self._draw_eye_partial(lx_adj, ey_adj, lr, blink_openness)
            self._draw_eye_partial(rx_adj, ey_adj, lr, blink_openness)
        else:
            self._draw_eye_open(lx_adj, ey_adj, lr, pdx, pdy)
            self._draw_eye_open(rx_adj, ey_adj, lr, pdx, pdy)

        # ── Blush (gentle thinking blush) ──
        blush_alpha = 0.28 + 0.08 * math.sin(t * 0.5)
        self._draw_blush(lx_adj, ey_adj, r, blush_alpha)
        self._draw_blush(rx_adj, ey_adj, r, blush_alpha)

        # ── Mouth: small circle that drifts side-to-side ("hmm... hmm...") ──
        my_adj = my + bob * 0.6
        mouth_drift = math.sin(t * 0.4) * sw * 0.012
        mouth_size = 0.016 + 0.003 * math.sin(t * 0.7)
        self._draw_mouth_o(mx_adj + mouth_drift, my_adj, sw, mouth_size)

        # ── Floating thought dots ──
        thought_x = rx_adj + lr * 1.8
        thought_y = ey_adj + lr * 0.8
        self._draw_thought_dots(thought_x, thought_y, r, t)

    # ── Speaking ──

    def _draw_speaking(self, lx, rx, ey, r, mx, my, sw):
        """Animated speaking: gentle eye bob, fixed mouth position,
        smooth sparkle/blush transitions, expressive eyes."""
        t = self._time()

        # ── Eye bob — gentle vertical movement (eyes only) ──
        bob = math.sin(t * 1.4) * r * 0.06
        sway = math.sin(t * 0.5 + 0.3) * r * 0.05

        ey_adj = ey + bob
        lx_adj = lx + sway
        rx_adj = rx + sway
        mx_adj = mx + sway

        lr = r * 1.15

        # ── Sparkle — smooth wave (0..1), fades in and out ──
        sparkle_raw = math.sin(t * 0.8 + 0.3)
        # Remap: only positive half becomes sparkle, smoothstepped
        sparkle = max(0.0, sparkle_raw)
        sparkle = sparkle * sparkle  # ease-in curve for gentle fade

        # ── Blush — follows sparkle but wider/softer envelope ──
        blush_raw = math.sin(t * 0.8 + 0.3)
        blush_alpha = max(0.0, blush_raw) * 0.40

        # ── Pupil liveliness ──
        pdx = 0.06 * math.sin(t * 0.8) + 0.03 * math.sin(t * 1.5)
        pdy = 0.03 * math.cos(t * 0.6)

        # ── Blink every ~5s ──
        blink_openness = 1.0
        blink_cycle = t % 5.0
        if blink_cycle > 4.7:
            blink_p = (blink_cycle - 4.7) / 0.3
            blink_openness = self._blink_curve(blink_p)

        # Secondary blink offset every ~8s
        blink2_cycle = (t + 3.0) % 8.0
        if blink2_cycle > 7.7 and blink_openness > 0.95:
            blink_p2 = (blink2_cycle - 7.7) / 0.3
            blink_openness = self._blink_curve(blink_p2)

        if blink_openness < 0.95:
            self._draw_eye_partial(lx_adj, ey_adj, lr, blink_openness)
            self._draw_eye_partial(rx_adj, ey_adj, lr, blink_openness)
        else:
            self._draw_eye_open(lx_adj, ey_adj, lr, pdx, pdy, sparkle)
            self._draw_eye_open(rx_adj, ey_adj, lr, pdx, pdy, sparkle)

        # ── Blush — smooth fade ──
        if blush_alpha > 0.02:
            self._draw_blush(lx_adj, ey_adj, r, blush_alpha)
            self._draw_blush(rx_adj, ey_adj, r, blush_alpha)

        # ── Mouth — faster oscillation, fixed vertical position ──
        mh_frac = (
            0.014
            + 0.007 * math.sin(t * 14.0)
            + 0.005 * math.sin(t * 9.5 + 0.7)
            + 0.003 * math.sin(t * 19.0 + 1.3)
        )
        mh_frac = max(0.004, mh_frac)
        mw_frac = 0.03 + 0.007 * math.sin(t * 8.5 + 0.5)

        Color(*self.MOUTH_COLOR)
        mw = sw * mw_frac
        mh = sw * mh_frac
        Ellipse(pos=(mx_adj - mw, my - mh), size=(mw * 2, mh * 2))
