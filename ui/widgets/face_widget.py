"""
Animated face widget for Zeina AI Assistant.

Canvas-drawn face with expressive eyes (pupils + highlights),
4 animation states with smooth procedural animation.
Supports swappable animation renderers and color themes.
"""
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, RoundedRectangle, Rectangle, Line
from kivy.graphics.scissor_instructions import ScissorPush, ScissorPop
from kivy.clock import Clock
from kivy.properties import StringProperty, NumericProperty
import math

from ui.animation_themes import BotRenderer, get_renderer


class FaceWidget(Widget):
    """Canvas-drawn face with state-responsive animations and theming."""

    state = StringProperty("idle")
    frame = NumericProperty(0)

    # Frame rate: 24fps for all states (smooth)
    FRAME_DELAY = 0.042

    # Colors (overridden by apply_theme)
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
        self._renderer = BotRenderer()
        # Smoothed mouth parameters for idle (avoids jarring size jumps)
        self._smile_w = 0.12
        self._smile_d = 0.044
        self.show_mouth = True  # Hidden when TTS is muted

        # Face-stream: response text rendered onto the canvas when chat + TTS are off
        self._stream_text = ""
        self._stream_alpha = 0.0   # 0 = invisible, 1 = fully visible
        self._stream_fading = False
        self._stream_timer = None  # Clock event that triggers the fade
        self._stream_font = "Roboto"  # Updated by apply_theme

        self.bind(size=self._redraw, pos=self._redraw)
        Clock.schedule_once(self._start_animation, 0)

    # ── Face-stream public API ───────────────────────────────────

    def begin_face_stream(self):
        """Start a new text stream on the face. Thread-safe."""
        Clock.schedule_once(self._begin_face_stream_main, 0)

    def append_face_token(self, token: str):
        """Append a token to the face stream. Thread-safe."""
        Clock.schedule_once(lambda dt: self._append_face_token_main(token), 0)

    def _begin_face_stream_main(self, dt):
        if self._stream_timer:
            self._stream_timer.cancel()
            self._stream_timer = None
        self._stream_text = ""
        self._stream_alpha = 1.0
        self._stream_fading = False

    _CHAR_MAP = str.maketrans({
        '\u2018': "'", '\u2019': "'",   # left/right single quotes
        '\u201c': '"', '\u201d': '"',   # left/right double quotes
        '\u2014': '--', '\u2013': '-',  # em dash, en dash
        '\u2026': '...', '\u2022': '-', # ellipsis, bullet
        '\u00b7': '-', '\u2019': "'",   # middle dot, right quote (repeat safe)
    })

    def _append_face_token_main(self, token: str):
        self._stream_text += token.translate(self._CHAR_MAP)
        self._stream_alpha = 1.0
        self._stream_fading = False
        # Reset fade timer — 2.5s after last token, start fading
        if self._stream_timer:
            self._stream_timer.cancel()
        self._stream_timer = Clock.schedule_once(self._begin_fade, 2.5)

    def _begin_fade(self, dt):
        self._stream_timer = None
        self._stream_fading = True

    def _start_animation(self, dt=None):
        self._anim_event = Clock.schedule_interval(self._tick, self.FRAME_DELAY)

    def _tick(self, dt):
        self._global_tick += 1
        # Advance face-stream fade (0.025 per frame ≈ 1.7s to fade out at 24fps)
        if self._stream_fading and self._stream_alpha > 0:
            self._stream_alpha = max(0.0, self._stream_alpha - 0.025)
            if self._stream_alpha <= 0:
                self._stream_text = ""
                self._stream_fading = False
        self._redraw()

    def set_state(self, new_state):
        if new_state == self.state:
            return
        self.state = new_state
        self._redraw()

    def set_animation_theme(self, name):
        """Switch to a different animation renderer."""
        self._renderer = get_renderer(name)

    def set_mouth_visible(self, visible: bool):
        """Show or hide the mouth — called when TTS mute is toggled."""
        self.show_mouth = visible

    def apply_theme(self, theme_dict):
        """Update colors from a theme dict."""
        self.SCREEN_COLOR = theme_dict.get("face_screen", self.SCREEN_COLOR)
        self.EYE_COLOR = theme_dict.get("face_eye", self.EYE_COLOR)
        self.PUPIL_COLOR = theme_dict.get("face_pupil", self.PUPIL_COLOR)
        self.MOUTH_COLOR = theme_dict.get("face_mouth", self.MOUTH_COLOR)
        self.SPARKLE_COLOR = theme_dict.get("face_sparkle", self.SPARKLE_COLOR)
        self.BLUSH_COLOR = theme_dict.get("face_blush", self.BLUSH_COLOR)
        self.BROW_COLOR = theme_dict.get("face_brow", self.BROW_COLOR)
        self.SIGNAL_COLOR = theme_dict.get("face_signal", self.SIGNAL_COLOR)
        self.MOUTH_INNER_COLOR = theme_dict.get("face_mouth_inner", self.MOUTH_INNER_COLOR)
        self.LIP_COLOR = theme_dict.get("face_lip", self.LIP_COLOR)
        self.TONGUE_COLOR = theme_dict.get("face_tongue", self.TONGUE_COLOR)
        self.THOUGHT_DOT_COLOR = theme_dict.get("face_thought_dot", self.THOUGHT_DOT_COLOR)
        self._stream_font = theme_dict.get("font_name", "Roboto")
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
        from ui.animation_themes import ASCIIRenderer
        scale_dim = min(sw, sh)
        # Vector only: shift eyes toward center when mouth is hidden (TTS muted).
        # ASCII renderer already centers its art between ey and my, so leave it alone.
        if not self.show_mouth and not isinstance(self._renderer, ASCIIRenderer):
            eye_y = sy + sh * 0.52
        else:
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
            self._renderer.draw_idle(self, lx, rx, eye_y, r, mx, my, sw)
        elif state == "listening":
            self._renderer.draw_listening(self, lx, rx, eye_y, r, mx, my, sw)
        elif state == "processing":
            self._renderer.draw_processing(self, lx, rx, eye_y, r, mx, my, sw)
        elif state == "speaking":
            self._renderer.draw_speaking(self, lx, rx, eye_y, r, mx, my, sw)

        if self._stream_text and self._stream_alpha > 0:
            self._draw_stream_text(sx, sy, sw, sh)

    def _draw_stream_text(self, sx, sy, sw, sh):
        """Render streaming response text onto the canvas below the eyes."""
        from kivy.core.text import Label as CoreLabel
        pad = sw * 0.07
        text_w = sw - pad * 2
        # Fixed font size — scale-to-fit handles overflow instead of dynamic sizing
        font_size = 53
        c = self.EYE_COLOR
        lbl = CoreLabel(
            text=self._stream_text,
            font_size=font_size,
            font_name=self._stream_font,
            color=(c[0], c[1], c[2], 1.0),
            halign='center',
            text_size=(text_w, None),
        )
        lbl.refresh()
        tex = lbl.texture
        if tex:
            tw, th = tex.size

            # Scale the drawn rectangle down to fit if the texture exceeds face bounds.
            # Only shrinks — never upscales short responses.
            max_h = sh * 0.90
            scale = min(text_w / tw, max_h / th, 1.0)
            draw_w = tw * scale
            draw_h = th * scale

            cx = sx + sw / 2 - draw_w / 2
            # Anchor text so it grows upward from just above the bottom of the face
            cy = sy + sh * 0.06

            scale_dim = min(sw, sh)
            r = scale_dim * 0.08
            sc = self.SCREEN_COLOR

            from ui.animation_themes import ASCIIRenderer
            text_top = cy + draw_h
            if isinstance(self._renderer, ASCIIRenderer):
                # ASCII mode: dim the art region only when text grows into it.
                # Art is centered at sh*0.5, spanning roughly sh*0.32 → sh*0.68.
                art_bottom = sy + sh * 0.32
                art_top = sy + sh * 0.68
                if text_top > art_bottom:
                    overlap_frac = min(1.0, (text_top - art_bottom) / (sh * 0.36))
                    art_alpha = min(0.78, overlap_frac * 0.78) * self._stream_alpha
                    Color(sc[0], sc[1], sc[2], art_alpha)
                    Rectangle(pos=(sx, art_bottom), size=(sw, art_top - art_bottom))
            else:
                # Vector mode: dim only the eye region when text grows into it.
                eye_y = sy + sh * (0.52 if not self.show_mouth else 0.65)
                eye_bottom = eye_y - r * 1.1   # just below the eye ellipses
                eye_top = eye_y + r * 1.8      # just above the brows
                if text_top > eye_bottom:
                    overlap_frac = min(1.0, (text_top - eye_bottom) / (r * 2.2))
                    eye_alpha = min(0.85, overlap_frac) * self._stream_alpha
                    Color(sc[0], sc[1], sc[2], eye_alpha)
                    Rectangle(
                        pos=(sx, eye_bottom - r * 0.3),
                        size=(sw, (eye_top - eye_bottom) + r * 0.5),
                    )

            # ScissorPush as a hard safety net for any rounding edge cases
            ScissorPush(x=int(sx), y=int(sy), width=int(sw), height=int(sh))
            Color(1, 1, 1, self._stream_alpha)
            Rectangle(pos=(cx, cy), size=(draw_w, draw_h), texture=tex)
            ScissorPop()

    # ── Eye primitives (shared toolkit for renderers) ──────────

    def _draw_eye_open(self, cx, cy, r, pupil_dx=0, pupil_dy=0, sparkle=0.0):
        """Draw an open eye. sparkle: 0.0 (off) to 1.0 (full sparkle)."""
        Color(*self.EYE_COLOR)
        Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2))
        pr = r * 0.45
        Color(*self.PUPIL_COLOR)
        Ellipse(
            pos=(cx + pupil_dx * r - pr, cy + pupil_dy * r - pr),
            size=(pr * 2, pr * 2),
        )
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
        """Smoothly animatable eye between closed (0) and open (1)."""
        Color(*self.EYE_COLOR)
        if openness <= 0.05:
            hw = r * 0.7
            Line(points=[cx - hw, cy, cx + hw, cy], width=1.6)
        else:
            h = r * 2 * max(0.08, openness)
            Ellipse(pos=(cx - r, cy - h / 2), size=(r * 2, h))
            if openness > 0.6:
                pr = r * 0.45 * openness
                Color(*self.PUPIL_COLOR)
                Ellipse(pos=(cx - pr, cy - pr), size=(pr * 2, pr * 2))
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
        """Cute cat-mouth / 'w' shape."""
        Color(*self.MOUTH_COLOR)
        mw = sw * width_frac
        pts = []
        for i in range(28):
            t = i / 27.0
            px = cx - mw + t * mw * 2
            py = y - abs(math.sin(t * math.pi * 2)) * (sw * 0.018)
            pts.extend([px, py])
        Line(points=pts, width=1.8)

    def _draw_mouth_pout(self, cx, y, sw, width_frac=0.05):
        """Small round pout."""
        Color(*self.MOUTH_COLOR)
        mr = sw * width_frac
        Ellipse(pos=(cx - mr * 0.7, y - mr), size=(mr * 1.4, mr * 2))

    # ── Accent primitives ───────────────────────────────────────

    def _draw_eyebrow(self, cx, cy, r, angle=0, width_frac=0.8):
        Color(*self.BROW_COLOR)
        bw = r * width_frac
        dy = r * 0.15 * angle
        pts = [cx - bw, cy + r * 1.4 + dy, cx + bw, cy + r * 1.4 - dy]
        Line(points=pts, width=1.6)

    def _draw_eyebrow_curved(self, cx, cy, r, furrow=0.0, is_left=True):
        """Curved anime-style eyebrow for thinking."""
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
        """Floating thought dots that drift upward."""
        for i in range(3):
            phase = t * 0.7 + i * 2.2
            loop_pos = (phase % 4.5) / 4.5
            if loop_pos > 1.0:
                continue
            drift_y = loop_pos * r * 3.5
            drift_x = math.sin(loop_pos * math.pi * 2 + i) * r * 0.6
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
