from typing import TypeVar, Generic
from .context import BaseAuthContext


# A TypeVar restricted to subclasses of BaseAuthContext.
# This ensures that any context passed to an Access Policy
# possesses the standard auth properties (is_admin, groups, etc.).
ContextType = TypeVar("ContextType", bound=BaseAuthContext)


class BaseAccessPolicy(Generic[ContextType]):
    """
    Base class for defining resource access policies.

    This class serves as a foundation for implementing Attribute-Based Access
    Control (ABAC) or Role-Based Access Control (RBAC) logic. It wraps the
    authentication context, providing a clean interface for permission checks.

    Attributes:
        ctx (ContextType): The authentication context containing user identity,
            groups, and role-specific data.
    """

    def __init__(self, ctx: ContextType):
        """
        Initializes the access policy with a specific user context.

        Args:
            ctx (ContextType): An instance of BaseAuthContext (or a subclass)
                representing the current user's session and permissions.
        """
        self.ctx: ContextType = ctx
