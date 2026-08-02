"""Bounded GUI selection capture with a headless fallback."""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict


class SelectionError(RuntimeError):
    pass


class SelectionCapture:
    def __init__(self, gui: Any = None, max_items: int = 128, max_sub_elements: int = 64):
        if not 1 <= max_items <= 4096 or not 1 <= max_sub_elements <= 1024:
            raise ValueError("selection bounds are invalid")
        self.gui = gui
        self.max_items = max_items
        self.max_sub_elements = max_sub_elements

    def _selection(self) -> Any:
        gui = self.gui
        if gui is None:
            try:
                import FreeCADGui as gui  # type: ignore
            except ImportError as exc:
                raise SelectionError("FreeCADGui is not available") from exc
        selection = getattr(gui, "Selection", None)
        if selection is None:
            raise SelectionError("FreeCAD selection API is unavailable")
        return selection

    def capture(self, clear: bool = False) -> Dict[str, Any]:
        selection = self._selection()
        getter = getattr(selection, "getSelectionEx", None)
        if not callable(getter):
            getter = getattr(selection, "getSelection", None)
        if not callable(getter):
            raise SelectionError("selection getter is unavailable")
        items = []
        for item in list(getter() or [])[: self.max_items]:
            obj = getattr(item, "Object", item)
            sub = getattr(item, "SubElementNames", []) or []
            items.append({
                "object": getattr(obj, "Name", getattr(obj, "Label", "")),
                "label": getattr(obj, "Label", ""),
                "type": getattr(obj, "TypeId", ""),
                "sub_elements": [str(name)[:128] for name in list(sub)[: self.max_sub_elements]],
            })
        if clear:
            remover = getattr(selection, "clearSelection", None)
            if callable(remover):
                remover()
        return {"items": items, "count": len(items), "truncated": len(list(getter() or [])) > self.max_items}

    def clear(self) -> None:
        selection = self._selection()
        remover = getattr(selection, "clearSelection", None)
        if callable(remover):
            remover()

    def set(self, items: Any) -> Dict[str, Any]:
        """Set GUI selection from explicit ``{object_name, subelements}`` items."""
        if not isinstance(items, list) or len(items) > self.max_items:
            raise SelectionError("selection items are invalid")
        selection = self._selection()
        clear = getattr(selection, "clearSelection", None)
        add = getattr(selection, "addSelection", None)
        if not callable(add):
            raise SelectionError("selection add API is unavailable")
        if callable(clear):
            clear()
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("object_name"), str):
                raise SelectionError("selection item is invalid")
            object_name = item["object_name"]
            subelements = item.get("subelements", [])
            if not isinstance(subelements, list) or len(subelements) > self.max_sub_elements:
                raise SelectionError("selection subelements are invalid")
            # FreeCADGui.Selection.addSelection accepts an object and optional
            # subelement; resolve objects through the active document only.
            gui_doc = getattr(self.gui, "ActiveDocument", None) if self.gui is not None else None
            obj = None
            if gui_doc is not None:
                obj = getattr(gui_doc, "getObject", lambda _name: None)(object_name)
            if obj is None:
                try:
                    import FreeCAD as app  # type: ignore
                    obj = getattr(app.ActiveDocument, "getObject", lambda _name: None)(object_name)
                except (ImportError, AttributeError):
                    obj = None
            if obj is None:
                raise SelectionError("selection object not found")
            if subelements:
                for subelement in subelements:
                    if not isinstance(subelement, str) or len(subelement) > 128:
                        raise SelectionError("selection subelement is invalid")
                    add(obj, subelement)
            else:
                add(obj)
        return self.capture()

    def capture_viewport(self, width: int = 1280, height: int = 720, scope: str = "viewport", image_format: str = "png") -> Dict[str, Any]:
        if not isinstance(width, int) or not isinstance(height, int) or not (16 <= width <= 8192 and 16 <= height <= 8192):
            raise SelectionError("viewport dimensions are invalid")
        if scope not in {"viewport", "window"}:
            raise SelectionError("capture scope is invalid")
        if image_format not in {"png", "jpeg"}:
            raise SelectionError("capture image format is invalid")
        gui = self.gui
        if gui is None:
            try:
                import FreeCADGui as gui  # type: ignore
            except ImportError as exc:
                raise SelectionError("FreeCADGui is not available") from exc
        extension = ".jpg" if image_format == "jpeg" else ".png"
        fd, path = tempfile.mkstemp(prefix="freecad-fem-mcp-", suffix=extension)
        os.close(fd)
        if scope == "window":
            window = getattr(gui, "getMainWindow", lambda: None)()
            grab = getattr(window, "grab", None) if window is not None else None
            if not callable(grab):
                raise SelectionError("window capture is unavailable")
            image = grab()
            saver = getattr(image, "save", None)
            if not callable(saver) or not saver(path, "JPEG" if image_format == "jpeg" else "PNG"):
                raise SelectionError("window capture failed")
        else:
            active_doc = getattr(gui, "activeDocument", lambda: None)()
            view = getattr(active_doc, "activeView", lambda: None)() if active_doc is not None else None
            saver = getattr(view, "saveImage", None)
            if not callable(saver):
                raise SelectionError("viewport capture is unavailable")
            saver(path, width, height, "Current")
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        if size > 16 * 1024 * 1024:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise SelectionError("capture exceeds size limit")
        return {"path": path, "scope": scope, "width": width, "height": height, "bytes": size, "format": image_format}
