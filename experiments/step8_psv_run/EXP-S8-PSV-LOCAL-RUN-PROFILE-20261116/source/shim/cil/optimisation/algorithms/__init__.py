import numpy as np


class Algorithm:
    """Minimal stand-in for cil.optimisation.algorithms.Algorithm (only what psv/petric use)."""

    def __init__(self, update_objective_interval=1, max_iteration=None, **kw):
        self.iteration = 0
        self.update_objective_interval = update_objective_interval
        self.max_iteration = np.inf

    def get_last_loss(self):
        return 0.0

    def run(self, iterations=np.inf, callbacks=None, verbose=0):
        callbacks = callbacks or []
        try:
            while self.iteration < iterations:
                self.update()
                self.iteration += 1
                for c in callbacks:
                    c(self)
        except StopIteration:
            pass
