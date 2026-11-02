"""Countdown without a GUI dependency (the timer functions are passed in, so it is easy to test)."""


class Countdown:
    def __init__(self, after, after_cancel, seconds, on_tick, on_done):
        self.after, self.after_cancel = after, after_cancel
        self.seconds, self.on_tick, self.on_done = int(seconds), on_tick, on_done
        self.remaining, self.active, self._h = 0, False, None

    def start(self):
        self.remaining, self.active = self.seconds, True
        self.on_tick(self.remaining)
        self._h = self.after(1000, self._step)

    def _step(self):
        if not self.active:
            return
        self.remaining -= 1
        if self.remaining <= 0:
            self.active = False
            self.on_done()
        else:
            self.on_tick(self.remaining)
            self._h = self.after(1000, self._step)

    def cancel(self):
        if self.active:
            self.active = False
            self.after_cancel(self._h)
