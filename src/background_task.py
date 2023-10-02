import threading

class BackgroundTask:
    def __init__(self, func):
        self._thread = threading.Thread(target=self._run, args=(func,))
        self._result = None
        self.exception = None
        self._done = False
        self._thread.start()

    def _run(self, func):
        try:
            self._result = func()
        except Exception as e:
            print(e)
            self.exception = e
        self._done = True

    def done(self):
        return self._done

    def result(self):
        return self._result


