"""
NetPulse desktop alert — Windows toast notification via winrt.
Falls back to a no-op when winrt is not available (CI, non-Windows).
"""

from __future__ import annotations

import sys


def notify(title: str, message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        from winrt.windows.ui.notifications import (
            ToastNotificationManager,
            ToastNotification,
            ToastTemplateType,
        )
        from winrt.windows.data.xml.dom import XmlDocument

        template = ToastNotificationManager.get_template_content(
            ToastTemplateType.TOAST_TEXT02
        )
        texts = template.get_elements_by_tag_name("text")
        texts[0].append_child(template.create_text_node(title))
        texts[1].append_child(template.create_text_node(message))

        notifier = ToastNotificationManager.create_toast_notifier("NetPulse")
        notifier.show(ToastNotification(template))
    except Exception:
        # winrt not installed or display unavailable — degrade silently.
        pass
