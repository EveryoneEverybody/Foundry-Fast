from importlib.machinery import SourceFileLoader
from pathlib import Path
import time


_base_path = Path(__file__).with_name("foundry_output_viewer.pyw")
base = SourceFileLoader("foundry_output_viewer_base", str(_base_path)).load_module()

_SPINNER_FRAMES = ("( | )", "( / )", "( - )", "( \\ )")
_SPINNER_INTERVAL_SECONDS = 0.20


class FoundryFastOutputWindow(base.FoundryOutputWindow):
    def __init__(self, arguments):
        super().__init__(arguments)
        self.spinner_index = 0
        self.spinner_updated_at = 0.0

    def _update_status_controls(self):
        status = self.export_status.status
        state = self.export_status.state

        if state == "active":
            now = time.monotonic()
            if now - self.spinner_updated_at >= _SPINNER_INTERVAL_SECONDS:
                self.spinner_index = (self.spinner_index + 1) % len(_SPINNER_FRAMES)
                self.spinner_updated_at = now
            status = f"{_SPINNER_FRAMES[self.spinner_index]} {status}"
        else:
            self.spinner_index = 0
            self.spinner_updated_at = 0.0

        rendered_status = (status, state)
        if rendered_status == self.rendered_status:
            return

        self.rendered_status = rendered_status
        base.user32.SetWindowTextW(self.status_label, status)
        flags = base.RDW_INVALIDATE | base.RDW_ERASE
        base.user32.RedrawWindow(self.status_border, None, None, flags)
        base.user32.RedrawWindow(self.status_label, None, None, flags)


if __name__ == "__main__":
    raise SystemExit(FoundryFastOutputWindow(base.parse_arguments()).run())
