"""Open the existing viewer and relay helper output without background threads."""
import codecs
from pathlib import Path


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
