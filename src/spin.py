import sys
import threading
import time

class Spinner:
    def __init__(self):
        self.i = 0
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.start()
        self.wrote = False

    def stop(self):
        self.running = False
        self.thread.join()
        if self.wrote:
            sys.stdout.write(chr(8) + " " + chr(8))
            sys.stdout.flush()

    def _run(self):
        bs = ""
        spinner = ["|", "/", "-", "\\"]
        i = 0
        while self.running:
            sys.stdout.write(bs + spinner[i % 4])
            bs = chr(8)
            sys.stdout.flush()
            self.wrote = True
            time.sleep(0.1)
            i += 1

def spin(f):
    s = Spinner()
    exc = None
    try:
        result = f()
    except Exception as e:
        exc = e
    s.stop()
    if exc:
        raise exc
    return result

