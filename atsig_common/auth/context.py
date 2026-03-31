from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .groups import GroupEnum


@dataclass
class SecretaryContext:
    """
    Contextual information for users with secretary roles.

    Attributes:
        department_id (int): The ID of the department the secretary belongs to.
        programme_ids (list[int]): List of IDs of academic programs managed by the secretary.
        call_ids (list[int]): List of IDs of calls for applications associated with the secretary.
    """

    department_id: int
    programme_ids: list[int]
    call_ids: list[int]


@dataclass
class EvaluatorContext:
    """
    Contextual information for users with evaluator roles.

    Attributes:
        call_ids (list[int]): List of IDs of calls that the evaluator is assigned to.
    """

    call_ids: list[int]


@dataclass
class AgentContext:
    """
    Contextual information for users acting as agents (Parent or Child).

    Attributes:
        sub_agents (list[str]): List of identifiers for subordinate agents.
        applicants (list[str]): List of identifiers for applicants associated with this agent.
    """

    sub_agents: list[str]
    applicants: list[str]


@dataclass
class BaseAuthContext:
    """
    Base class for handling user authentication and authorization context.

    This class stores user identity information, group memberships, and handles
    the lazy loading of role-specific contexts (Secretary, Agent, Evaluator).
    """

    sub: str
    email: str
    groups: list[str]
    given_name: str
    family_name: str
    department_id: int | None = None

    def has_group(self, suffix: GroupEnum) -> bool:
        """
        Checks if the user belongs to a specific group by matching the group name suffix.

        Args:
            suffix (GroupEnum): The group type to check for.

        Returns:
            bool: True if any group name ends with the specified suffix value.
        """
        return any(group.endswith(suffix.value) for group in self.groups)

    @property
    def is_admin(self):
        """bool: Indicates if the user has administrative privileges."""
        return self.has_group(GroupEnum.ADMIN)

    @property
    def is_secretary(self) -> bool:
        """bool: Indicates if the user has any type of secretary role."""
        return self.is_program_secretary or self.is_department_secretary

    @property
    def is_department_secretary(self) -> bool:
        """bool: Indicates if the user is a department-level secretary."""
        return self.has_group(GroupEnum.DEPARTMENT_SECRETARY)

    @property
    def is_program_secretary(self) -> bool:
        """bool: Indicates if the user is a program-level secretary."""
        return self.has_group(GroupEnum.PROGRAM_SECRETARY)

    @property
    def is_evaluator(self):
        """bool: Indicates if the user is an evaluator."""
        return self.has_group(GroupEnum.EVALUATOR)

    @property
    def is_applicant(self):
        """bool: Indicates if the user is an applicant."""
        return self.has_group(GroupEnum.APPLICANT)

    @property
    def is_agent(self) -> bool:
        """bool: Indicates if the user is either a parent or a child agent."""
        return self.is_parent_agent or self.is_child_agent

    @property
    def is_child_agent(self) -> bool:
        """bool: Indicates if the user is a child agent."""
        return self.has_group(GroupEnum.CHILD_AGENT)

    @property
    def is_parent_agent(self) -> bool:
        """bool: Indicates if the user is a parent agent."""
        return self.has_group(GroupEnum.PARENT_AGENT)

    # Optional sub-contexts initialized upon request
    secretary: SecretaryContext | None = None
    agent: AgentContext | None = None
    evaluator: EvaluatorContext | None = None

    async def load_role_contexts(self, session: AsyncSession) -> "AuthContext":
        """
        Loads all applicable role contexts for the user based on their group memberships.

        This method checks for secretary, agent, and evaluator roles and fetches
        their respective data if they haven't been loaded yet. It assumes that
        different secretary scopes are independent.

        Args:
            session (AsyncSession): The database session to use for fetching context data.

        Returns:
            BaseAuthContext: The updated instance with loaded contexts.
        """

        if self.is_secretary and self.secretary is None:
            self.secretary = await self.load_secretary_context(session=session)

        if self.is_agent and self.agent is None:
            self.agent = await self.load_agent_context(session=session)

        if self.is_evaluator and self.evaluator is None:
            self.evaluator = await self.load_evaluator_context(session=session)

        return self

    async def load_secretary_context(self, session: AsyncSession) -> SecretaryContext:
        """
        Fetches the specific context for a secretary from the database.

        Args:
            session (AsyncSession): The active database session.
        """
        pass

    async def load_agent_context(self, session: AsyncSession) -> AgentContext:
        """
        Fetches the specific context for an agent from the database.

        Args:
            session (AsyncSession): The active database session.
        """
        pass

    async def load_evaluator_context(self, session: AsyncSession) -> EvaluatorContext:
        """
        Fetches the specific context for an evaluator from the database.

        Args:
            session (AsyncSession): The active database session.
        """
        pass
