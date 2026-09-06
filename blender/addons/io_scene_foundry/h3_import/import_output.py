"""Open the existing viewer and relay helper output without background threads."""
import codecs
import time
from pathlib import Path


class ImportProgress:
    """The parent import owns completion, including work after helper exit."""
    def __init__(self, label, area=None, clock=time.monotonic, emit=print):
        self.label, self.area, self.clock, self.emit = label, area, clock, emit
        self.started = clock()
        self.last_time = float('-inf')
        self.last_message = None
        self.finished = False

    def update(self, message, force=False):
        if self.finished:
            return
        message = ' '.join(str(message).split())
        elapsed = self.clock() - self.started
        if self.area is not None:
            self.area.header_text_set(f'H3 {self.label}: {message} | {elapsed:.1f}s | Esc: cancel')
        if force or (message != self.last_message and self.clock() - self.last_time >= 1):
            self.emit(f'[H3 import active] {self.label}: {message}', flush=True)
            self.last_message, self.last_time = message, self.clock()

    def finish(self, state):
        if not self.finished:
            self.finished = True
            self.emit(f'[H3 import {state}] {self.label}: {state} after {self.clock() - self.started:.1f}s', flush=True)


def open_output(utils, host):
    if getattr(getattr(host, 'app', None), 'background', False):
        return
    try:
        utils.show_output()
    except Exception as error:
        print(f'Foundry Output could not open: {error}')


class HelperLogTail:
    def __init__(self):
        self.path = None
        self.offset = 0
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.tail = ''

    def follow(self, path):
        self.path = Path(path)
        self.offset = 0
        self.decoder.reset()
        self.tail = ''

    def poll(self, final=False):
        if self.path is None:
            return self.tail
        with self.path.open('rb') as handle:
            handle.seek(self.offset)
            while True:
                data = handle.read(65536)
                self.offset += len(data)
                text = self.decoder.decode(data, final=final and not data)
                if text:
                    self.tail = (self.tail + text)[-2000:]
                    print(text, end='', flush=True)
                if not final or not data:
                    break
        return self.tail
