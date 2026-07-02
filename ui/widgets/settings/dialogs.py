"""Shared popup dialogs for the settings screen.

All the destructive actions (clear memory, clear history, reset personality,
delete profile) share one confirmation popup builder instead of four
hand-rolled copies.
"""
from __future__ import annotations

from typing import Callable

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup

DANGER_COLOR = (0.75, 0.15, 0.15, 0.95)
CANCEL_BG = (0.22, 0.22, 0.26, 1)
POPUP_BG = (0.1, 0.1, 0.12, 0.98)


def confirm_popup(
    *,
    message: str,
    confirm_text: str,
    on_confirm: Callable[[], None],
    font: str = "Roboto",
    title: str = "",
    message_height: int = 32,
    size_hint: tuple = (0.65, 0.28),
    confirm_color: tuple = DANGER_COLOR,
    show_cancel: bool = True,
) -> None:
    """Show a confirmation popup; runs ``on_confirm`` after dismissing."""
    content = BoxLayout(orientation='vertical', spacing=14, padding=[20, 16])
    content.add_widget(Label(
        text=message,
        font_size='14sp',
        font_name=font,
        color=(0.9, 0.9, 0.9, 1),
        size_hint_y=None,
        height=message_height,
        halign='center',
    ))

    popup = Popup(
        title=title,
        separator_height=0 if not title else 2,
        content=content,
        size_hint=size_hint,
        background_color=POPUP_BG,
    )

    btn_row = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=44)

    if show_cancel:
        cancel_btn = Button(
            text="Cancel", font_size='14sp', font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=CANCEL_BG, color=(0.7, 0.7, 0.75, 1),
        )
        cancel_btn.bind(on_release=lambda x: popup.dismiss())
        btn_row.add_widget(cancel_btn)

    confirm_btn = Button(
        text=confirm_text, font_size='14sp', font_name=font,
        background_normal='atlas://data/images/defaulttheme/button',
        background_color=confirm_color, color=(1, 1, 1, 0.95),
    )

    def _do_confirm(instance) -> None:
        popup.dismiss()
        on_confirm()

    confirm_btn.bind(on_release=_do_confirm)
    btn_row.add_widget(confirm_btn)
    content.add_widget(btn_row)
    popup.open()


def info_popup(*, title: str, message: str, font: str = "Roboto") -> None:
    """Show a dismissable informational popup."""
    popup = Popup(
        title=title,
        content=Label(text=message, font_name=font, font_size='13sp'),
        size_hint=(0.6, 0.22),
        background_color=POPUP_BG,
    )
    popup.open()
