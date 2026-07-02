"""Model selector popup (Ctrl+M) — pick a chat model from the served list."""
from __future__ import annotations

from typing import TYPE_CHECKING

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from zeina import config, llm

if TYPE_CHECKING:
    from ui.app import ZeinaApp


def show_model_selector(app: "ZeinaApp") -> None:
    """Show a Kivy Popup listing the models served by the backend."""
    models = llm.list_model_ids()
    if not models:
        app._status.set_status("No models served (is the model server running?)", "red")
        return

    bot_name = app._settings.get("bot_name", "Zeina")

    content = BoxLayout(orientation='vertical', spacing=10, padding=[16, 12])

    title_label = Label(
        text="Select Model",
        font_size='16sp',
        size_hint_y=None,
        height=30,
        color=(0.85, 0.88, 0.92, 1),
        bold=True,
    )
    content.add_widget(title_label)

    scroll = ScrollView(do_scroll_x=False)
    model_list = BoxLayout(
        orientation='vertical',
        size_hint_y=None,
        spacing=8,
        padding=[4, 4],
    )
    model_list.bind(minimum_height=model_list.setter('height'))

    popup = Popup(
        title="",
        separator_height=0,
        size_hint=(0.85, 0.65),
        background_color=(0.1, 0.1, 0.12, 0.98),
    )

    def select_model(model_name: str) -> None:
        if model_name != config.CHAT_MODEL:
            config.CHAT_MODEL = model_name
            app._settings.set("chat_model", model_name)
            app._kivy_display.show_menu_bar(app._assistant.mode, bot_name)
        popup.dismiss()

    for name in models:
        is_current = name == config.CHAT_MODEL
        btn = Button(
            text=f"> {name}" if is_current else f"  {name}",
            size_hint_y=None,
            height=48,
            font_size='14sp',
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.18, 0.52, 0.46, 1) if is_current else (0.15, 0.16, 0.2, 1),
            color=(1, 1, 1, 0.95),
        )
        btn.bind(on_release=lambda x, n=name: select_model(n))
        model_list.add_widget(btn)

    scroll.add_widget(model_list)
    content.add_widget(scroll)

    cancel_btn = Button(
        text="Cancel",
        size_hint_y=None,
        height=44,
        font_size='14sp',
        background_normal='atlas://data/images/defaulttheme/button',
        background_color=(0.22, 0.22, 0.26, 1),
        color=(0.7, 0.7, 0.75, 1),
    )
    cancel_btn.bind(on_release=lambda x: popup.dismiss())
    content.add_widget(cancel_btn)

    popup.content = content
    popup.open()
