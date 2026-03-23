from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.policy import BaseAccessPolicy


class BaseService:
    """The ultimate base: DB, no Auth"""

    def __init__(self, session: AsyncSession):
        self.session = session


class BaseAuthService(BaseService):
    """Requires Strict Auth Policy"""

    def __init__(self, session: AsyncSession, policy: BaseAccessPolicy):
        super().__init__(session)
        self.policy = policy
        self.ctx = policy.ctx


class BaseOptionalAuthService(BaseService):
    """Optional Auth Policy"""

    def __init__(
        self, session: AsyncSession, policy: Optional[BaseAccessPolicy] = None
    ):
        super().__init__(session)
        self.policy = policy
        self.ctx = policy.ctx if policy else None
