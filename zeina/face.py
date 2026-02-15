"""
Animated face display for Zeina AI Assistant
"""
from rich.panel import Panel
from rich.align import Align
from rich.text import Text
from zeina.enums import RecordingState


class Face:
    """Animated ASCII face that responds to assistant state"""

    # Eye direction characters:
    #   ◕  = default big eye (cute, mostly filled)
    #   ◑  = pupil right        ◐  = pupil left
    #   ◓  = pupil up           ◒  = pupil down
    #   ◔  = small quarter fill (thinking / glancing)
    #   ●  = solid (alert)      ◉  = bullseye (intense focus)
    #   ✧  = sparkle            ◠  = happy squint
    #   ◡  = half-closed        ─  = fully closed (blink)

    FACES = {

        # ─────────────────────────────────────────────────
        # IDLE – long natural cycle with eye movement,
        #        blinks, glances, and personality moments
        #        (~18 s at 0.55 s/frame)
        # ─────────────────────────────────────────────────
        "idle": [
            # --- resting happy (hold) ---
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            # --- glance right ---
            """
        ◑   ◑
          ω
            """,
            """
        ◑   ◑
          ω
            """,
            # --- back to center ---
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            # --- blink ---
            """
        ◡   ◡
          ω
            """,
            """
        ─   ─
          ᴗ
            """,
            """
        ◡   ◡
          ω
            """,
            # --- resting (hold) ---
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            # --- glance left ---
            """
        ◐   ◐
          ω
            """,
            """
        ◐   ◐
          ω
            """,
            # --- back to center, soft smile ---
            """
        ◕   ◕
          ᴗ
            """,
            """
        ◕   ◕
          ᴗ
            """,
            # --- blink ---
            """
        ◡   ◡
          ᴗ
            """,
            """
        ─   ─
          ᴗ
            """,
            """
        ◡   ◡
          ω
            """,
            # --- resting (hold) ---
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            # --- sparkle! ---
            """
        ✧   ✧
          ω
            """,
            """
        ✧   ✧
          ω
            """,
            # --- happy squint ---
            """
        ◠   ◠
          ω
            """,
            # --- back to normal ---
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            # --- look up briefly ---
            """
        ◓   ◓
          ω
            """,
            """
        ◓   ◓
          ω
            """,
            # --- back to center (hold) ---
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            """
        ◕   ◕
          ω
            """,
            # --- quick blink ---
            """
        ─   ─
          ᴗ
            """,
            """
        ◕   ◕
          ω
            """,
        ],

        # ─────────────────────────────────────────────────
        # LISTENING – wide-eyed, locked in, attentive
        # ─────────────────────────────────────────────────
        "listening": [
            """
        ●   ●
          ○
            """,
            """
        ●   ●
          ○
            """,
            """
        ◉   ◉
          ○
            """,
            """
        ●   ●
          ◎
            """,
            """
        ◉   ◉
          ○
            """,
            """
        ●   ●
          ○
            """,
        ],

        # ─────────────────────────────────────────────────
        # PROCESSING – thinking hard, eyes darting around
        # ─────────────────────────────────────────────────
        "processing": [
            """
        ◔   ◔
          ~
            """,
            """
        ◑   ◑
          ~
            """,
            """
        ◕   ◕
          ~
            """,
            """
        ◐   ◐
          ~
            """,
            """
        ◓   ◓
          ~
            """,
            """
        ◕   ◕
          ~
            """,
            """
        ◔   ◔
          ~
            """,
        ],

        # ─────────────────────────────────────────────────
        # SPEAKING – lively mouth cycle with expressive eyes
        # ─────────────────────────────────────────────────
        "speaking": [
            # soft start
            """
        ◕   ◕
          ◡
            """,
            # open
            """
        ◕   ◕
          ○
            """,
            # wide
            """
        ◕   ◕
          ◠
            """,
            # rounded
            """
        ◕   ◕
          o
            """,
            # sparkle emphasis
            """
        ✧   ✧
          ○
            """,
            # return
            """
        ◕   ◕
          ◡
            """,
            # open again
            """
        ◕   ◕
          ○
            """,
            # happy
            """
        ◕   ◕
          ◠
            """,
            # soft close
            """
        ◕   ◕
          ◡
            """,
        ]
    }

    def __init__(self):
        self.current_state = "idle"
        self.frame_index = 0
        self.blink_counter = 0

    def get_face(self) -> str:
        """Get current frame of face animation"""
        faces = self.FACES.get(self.current_state, self.FACES["idle"])

        # Cycle through animation frames
        face = faces[self.frame_index % len(faces)]

        return face

    def update_state(self, state: str):
        """Update face state"""
        if state != self.current_state:
            self.current_state = state
            self.frame_index = 0
        else:
            self.frame_index += 1

    def get_frame_delay(self) -> float:
        """Return animation delay based on current state"""
        delays = {
            "idle": 0.55,
            "listening": 0.25,
            "processing": 0.18,
            "thinking": 0.22,
            "speaking": 0.14
        }
        return delays.get(self.current_state, 0.3)

    def get_state_from_recording_state(self, recording_state: RecordingState, is_speaking: bool) -> str:
        """Map recording state to face state"""
        if is_speaking:
            return "speaking"
        elif recording_state == RecordingState.LISTENING:
            return "listening"
        elif recording_state == RecordingState.PROCESSING:
            return "processing"
        else:
            return "idle"

    def render(self, state: str = None, title: str = "Zeina") -> Panel:
        """Render face in a panel"""
        if state:
            self.update_state(state)

        face_text = Text(self.get_face(), style="bold cyan", justify="center")

        return Panel(
            Align.center(face_text, vertical="middle"),
            border_style="cyan",
            height=10
        )
