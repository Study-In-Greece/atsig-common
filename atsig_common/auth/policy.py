from .context import BaseAuthContext


class BaseAccessPolicy:
    def __init__(self, ctx: BaseAuthContext):
        self.ctx = ctx
