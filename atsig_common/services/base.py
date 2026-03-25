from typing import Optional, TypeVar, Generic
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.policy import BaseAccessPolicy

# Generic type για Policy
PolicyType = TypeVar("PolicyType", bound=BaseAccessPolicy)


class BaseService:
    """The ultimate base: DB, no Auth"""

    def __init__(self, session: AsyncSession):
        self.session = session


class BaseAuthService(BaseService, Generic[PolicyType]):
    """Requires Strict Auth Policy"""

    def __init__(self, session: AsyncSession, policy: PolicyType):
        super().__init__(session)
        self.policy: PolicyType = policy
        self.ctx = policy.ctx


class BaseOptionalAuthService(BaseService, Generic[PolicyType]):
    """Optional Auth Policy"""

    def __init__(
        self,
        session: AsyncSession,
        policy: Optional[PolicyType] = None,
    ):
        super().__init__(session)
        self.policy: Optional[PolicyType] = policy
        self.ctx = policy.ctx if policy else None
