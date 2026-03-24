from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .groups import GroupEnum


@dataclass
class SecretaryContext:
    department_id: int
    programme_ids: list[int]
    call_ids: list[int]


@dataclass
class EvaluatorContext:
    call_ids: list[int]


@dataclass
class AgentContext:
    sub_agents: list[str]
    applicants: list[str]


@dataclass
class BaseAuthContext:
    sub: str
    email: str
    bearer_token: str
    groups: list[str]
    given_name: str
    family_name: str
    department_id: int | None = None

    def has_group(self, suffix: GroupEnum) -> bool:
        return any(group.endswith(suffix.value) for group in self.groups)

    @property
    def is_admin(self):
        return self.has_group(GroupEnum.ADMIN)

    @property
    def is_secretary(self) -> bool:
        return self.is_program_secretary or self.is_department_secretary

    @property
    def is_department_secretary(self) -> bool:
        return self.has_group(GroupEnum.DEPARTMENT_SECRETARY)

    @property
    def is_program_secretary(self) -> bool:
        return self.has_group(GroupEnum.PROGRAM_SECRETARY)

    @property
    def is_evaluator(self):
        return self.has_group(GroupEnum.EVALUATOR)

    @property
    def is_applicant(self):
        return self.has_group(GroupEnum.APPLICANT)

    @property
    def is_agent(self) -> bool:
        return self.is_parent_agent or self.is_child_agent

    @property
    def is_child_agent(self) -> bool:
        return self.has_group(GroupEnum.CHILD_AGENT)

    @property
    def is_parent_agent(self) -> bool:
        return self.has_group(GroupEnum.PARENT_AGENT)

    secretary: SecretaryContext | None = None
    agent: AgentContext | None = None
    evaluator: EvaluatorContext | None = None

    async def load_role_contexts(self, session: AsyncSession) -> "AuthContext":
        """
        Loads role contexts.
        Assumes secretary scopes are independent.
        """

        if self.is_secretary and self.secretary is None:
            self.secretary = await self.load_secretary_context(session=session)

        if self.is_agent and self.agent is None:
            self.agent = await self.load_agent_context(session=session)

        if self.is_evaluator and self.evaluator is None:
            self.evaluator = await self.load_evaluator_context(session=session)

        return self

    async def load_secretary_context(self, session: AsyncSession) -> SecretaryContext:
        pass

    async def load_agent_context(self, session: AsyncSession) -> AgentContext:
        pass

    async def load_evaluator_context(self, session: AsyncSession) -> EvaluatorContext:
        pass