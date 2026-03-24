from typing import TypeVar, Generic

from .context import BaseAuthContext


ContextType = TypeVar("ContextType", bound=BaseAuthContext)

class BaseAccessPolicy(Generic[ContextType]):
    def __init__(self, ctx: BaseAuthContext):
        self.ctx = ctx
