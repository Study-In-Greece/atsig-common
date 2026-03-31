from enum import Enum


class GroupEnum(str, Enum):
    """
    Enumeration of Keycloak group paths used for RBAC (Role-Based Access Control).

    Values represent the exact path of the group in Keycloak.
    """

    EVALUATOR = "/Evaluators"
    APPLICANT = "/Applicants"
    SECRETARY = "/Secretary"
    DEPARTMENT_SECRETARY = "/Secretary/Department"
    PROGRAM_SECRETARY = "/Secretary/Program"
    ADMIN = "/Administrators"
    HELPDESK = "/Helpdesk"
    AGENT = "/Agents"
    PARENT_AGENT = "/Agents/Parent"
    CHILD_AGENT = "/Agents/Child"


# Groups with elevated privileges that can bypass standard scope checks
SUPER_GROUPS = [GroupEnum.HELPDESK.value, GroupEnum.ADMIN.value]

# Primary user classifications
MAIN_GROUPS = [
    GroupEnum.APPLICANT.value,
    GroupEnum.SECRETARY.value,
    GroupEnum.EVALUATOR.value,
    GroupEnum.AGENT.value,
]


def validate_user_groups(
    user_groups: list[str],
    required_scopes: list[str],
    super_groups: list[str] = SUPER_GROUPS,
) -> bool:
    """
    Validates user access based on group membership and required scopes.

    This function implements a hierarchical check. If a user belongs to a parent
    group (e.g., '/Secretary'), they are automatically granted access to
    resources requiring a sub-group (e.g., '/Secretary/Program').

    Args:
        user_groups (list[str]): The list of groups assigned to the user from the token.
        required_scopes (list[str]): The list of group paths required to access a resource.
        super_groups (list[str], optional): Groups that bypass validation. Defaults to SUPER_GROUPS.

    Returns:
        bool: True if the user has a matching or parent group, or belongs to a super group.
              False otherwise.
    """

    # 1. Bypass check: If the user belongs to a Super Group, grant access immediately
    if any(group in user_groups for group in super_groups):
        return True

    # 2. If no specific scopes are required, the authenticated user is allowed
    if not required_scopes:
        return True

    # 3. Hierarchy Check:
    # Check if any of the user's groups match the required scope exactly
    # or act as a parent path (e.g., /Secretary allows access to /Secretary/Program)
    for required in required_scopes:
        for user_group in user_groups:
            if user_group == required or user_group.startswith(f"{required}/"):
                return True

    return False
