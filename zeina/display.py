"""
Display/UI components for Zeina AI Assistant
"""
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from zeina.enums import InteractionMode, RecordingState
from zeina.face import Face
import threading
import time
import sys


class Display:
    """Manages Rich terminal UI with animated face"""

    def __init__(self):
        self.console = Console()  # Main console for messages
        self.face = Face()
        self.face_update_thread = None
        self.stop_face_updates = False
        self.pause_face_updates = False  # Pause rendering without stopping thread
        self.face_visible = False
        self.status_line = ""  # Current status to display
        self.status_style = "cyan"
        self.status_detail_line = ""  # Secondary status line
        self.status_detail_style = "dim"
        self.face_lines = 0  # Track how many lines the face area uses
        self.content_start_line = 0  # Where content printing starts
        self.current_mode = InteractionMode.VOICE  # Track current mode for menu bar
        self.current_model = ""  # Track current model name for menu bar

    def show_status(self, status: str, style: str = ""):
        """Show a status message"""
        if style:
            self.console.print(f"[{style}]{status}[/{style}]")
        else:
            self.console.print(status)

    def show_header(self):
        """Show application header"""
        self.console.print(Panel.fit(
            "[bold cyan]🤖 Zeina AI Assistant[/bold cyan]\n"
            "[dim]Press SPACE to talk | TAB to toggle mode | Ctrl+M to change model | ESC to quit[/dim]",
            border_style="cyan"
        ))
        self.console.print()

    def show_menu_bar(self, mode: InteractionMode, model_name: str):
        """Update menu bar with current mode and model (will be rendered by face animation)"""
        self.current_mode = mode
        self.current_model = model_name

    def show_user_message(self, message: str):
        """Show user's message"""
        self.move_cursor_to_feed_bottom()
        self.console.print(Panel(
            f"[bold green]You:[/bold green] {message}",
            border_style="green"
        ))

    def show_assistant_message(self, message: str):
        """Show assistant's message"""
        self.move_cursor_to_feed_bottom()
        self.console.print(Panel(
            f"[bold blue]Zeina:[/bold blue] {message}",
            border_style="blue"
        ))

    def show_error(self, message: str):
        """Show error message"""
        self.move_cursor_to_feed_bottom()
        self.console.print(f"[bold red]❌ {message}[/bold red]")

    def show_info(self, message: str):
        """Show info message"""
        self.move_cursor_to_feed_bottom()
        self.console.print(f"[cyan]{message}[/cyan]")

    def show_status_centered(self, message: str, style: str = "cyan"):
        """Update the fixed status line above the text feed"""
        self.status_line = message
        self.status_style = style
        # The status will be updated by the face animation thread

    def show_status_detail_centered(self, message: str, style: str = "dim"):
        """Update the secondary status line above the text feed"""
        self.status_detail_line = message
        self.status_detail_style = style
        # The status will be updated by the face animation thread

    def start_face_display(self, clear_screen: bool = True):
        """Start the animated face display at the top of terminal"""
        self.face_visible = True
        self.stop_face_updates = False  # Reset stop flag

        # Calculate face area height (menu bar + face panel + status line + blank line)
        # Menu bar: 2 lines + Face panel: 14 lines + status line + detail + blank = ~20 lines
        self.face_lines = 20

        # Set scrolling region: top portion (face area) is fixed, rest scrolls
        # DECSTBM: \033[top;bottomr sets scrolling region
        # We want lines (face_lines+1) to bottom to scroll
        sys.stdout.write(f"\033[{self.face_lines + 1};r")
        sys.stdout.flush()

        if clear_screen:
            # Clear screen and move to home
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

        def animate_face():
            """Animate face in a loop by updating in place"""
            while not self.stop_face_updates:
                # Skip rendering if paused (e.g., during chat input)
                if self.pause_face_updates:
                    time.sleep(0.3)
                    continue

                # Update to next animation frame
                self.face.frame_index += 1

                # Save current cursor position (in scrolling region)
                sys.stdout.write("\0337")  # DECSC - save cursor

                # Move to top of screen (face area - not in scrolling region)
                sys.stdout.write("\033[H")

                # Render menu bar, face, and status together
                from io import StringIO

                string_buffer = StringIO()
                temp_console = Console(file=string_buffer, force_terminal=True, width=self.console.width)

                # Render menu bar at the top
                voice_style = "bold green" if self.current_mode == InteractionMode.VOICE else "dim"
                chat_style = "bold green" if self.current_mode == InteractionMode.CHAT else "dim"

                menu_text = (
                    f"[{voice_style}]● Voice[/{voice_style}]  "
                    f"[{chat_style}]● Chat[/{chat_style}]  "
                    f"[dim](TAB to toggle)[/dim]  |  "
                    f"Model: [bold cyan]{self.current_model}[/bold cyan]  "
                    f"[dim](Ctrl+M to change)[/dim]"
                )
                temp_console.print(menu_text)
                temp_console.print()  # Blank line after menu

                # Render face
                face_panel = self.face.render()
                temp_console.print(face_panel, end="")

                # Render status line centered below face
                if self.status_line:
                    from rich.align import Align
                    status_text = Text(self.status_line, style=self.status_style, justify="center")
                    temp_console.print(Align.center(status_text))
                if self.status_detail_line:
                    from rich.align import Align
                    detail_text = Text(self.status_detail_line, style=self.status_detail_style, justify="center")
                    temp_console.print(Align.center(detail_text))
                temp_console.print()  # Blank line after status

                combined_str = string_buffer.getvalue()

                # Write face area (will not affect scrolling region)
                lines = combined_str.rstrip('\n').split('\n')
                for i, line in enumerate(lines[:self.face_lines]):
                    # Position cursor at start of this line
                    sys.stdout.write(f'\033[{i + 1};1H')
                    # Clear line
                    sys.stdout.write('\033[2K')
                    # Write content
                    sys.stdout.write(line)

                # Restore cursor position (back to scrolling region)
                sys.stdout.write("\0338")  # DECRC - restore cursor
                sys.stdout.flush()

                time.sleep(self.face.get_frame_delay())  # Animation frame rate

        # Start animation in background thread
        self.face_update_thread = threading.Thread(target=animate_face, daemon=True)
        self.face_update_thread.start()

        if clear_screen:
            # Move cursor to content area (line face_lines + 1)
            time.sleep(0.1)  # Let face render once
            sys.stdout.write(f"\033[{self.face_lines + 1};1H")
            sys.stdout.flush()

    def update_face_state(self, recording_state: RecordingState, is_speaking: bool = False):
        """Update face expression based on assistant state"""
        face_state = self.face.get_state_from_recording_state(recording_state, is_speaking)
        self.face.update_state(face_state)
        # The animation thread will automatically pick up the new state

    def move_cursor_to_content_area(self):
        """Move cursor to the content area (below face) - useful after mode changes"""
        if self.face_visible:
            # Move to content area without specifying exact line (let terminal auto-position)
            # Just ensure we're past the face area
            sys.stdout.write(f"\033[{self.face_lines + 1};1H")
            sys.stdout.flush()

    def clear_feed(self):
        """Clear the scrolling feed area (below the face)"""
        if self.face_visible:
            sys.stdout.write("\0337")  # Save cursor
            # Clear each line in the scrolling region
            term_height = self.console.height or 50
            for i in range(self.face_lines + 1, term_height + 1):
                sys.stdout.write(f"\033[{i};1H\033[2K")
            # Move cursor to top of scrolling region
            sys.stdout.write(f"\033[{self.face_lines + 1};1H")
            sys.stdout.write("\0338")  # Restore cursor
            sys.stdout.flush()

    def move_cursor_to_feed_bottom(self):
        """Move cursor to the bottom of the scrolling feed"""
        if self.face_visible:
            # Jump to the top of the scrolling region, then move down to its bottom.
            sys.stdout.write(f"\033[{self.face_lines + 1};1H\033[999B")
            sys.stdout.flush()

    def stop_face_display(self, clear_screen: bool = True):
        """Stop the face display"""
        self.stop_face_updates = True
        if self.face_update_thread:
            self.face_update_thread.join(timeout=1.0)

        # Reset scrolling region to full screen
        sys.stdout.write("\033[r")
        if clear_screen:
            # Clear screen
            sys.stdout.write("\033[2J\033[H")
        # Show cursor (in case it was hidden)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

        self.face_visible = False
