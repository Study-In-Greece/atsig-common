from enum import Enum


class GroupEnum(str, Enum):
    EVALUATOR = "/Evaluators"
    APPLICANT = "/Applicants"
    SECRETARY = "/Secretary"
    DEPARTMENT_SECRETARY = "/Secretary/Department"
    PROGRAM_SECRETARY = "/Secretary/Program"
    ADMIN = "/Administrators"
    HELPDESK = "/Helpdesk"
    AGENT = "/Agents"
    PARENT_AGENT = "/Agent/Parent"
    CHILD_AGENT = "/Agent/Child"


SUPER_GROUPS = [GroupEnum.HELPDESK.value, GroupEnum.ADMIN.value]

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
    Ελέγχει αν ο χρήστης έχει πρόσβαση βάσει των groups του.
    Υποστηρίζει ιεραρχικό έλεγχο (π.χ. /Secretary επιτρέπει το /Secretary/Program).
    """

    # 1. Bypass αν ο χρήστης ανήκει σε Super Group
    if any(group in user_groups for group in super_groups):
        return True

    # 2. Αν δεν απαιτούνται συγκεκριμένα scopes, ο χρήστης περνάει (αφού είναι authenticated)
    if not required_scopes:
        return True

    # 3. Ιεραρχικός έλεγχος (Hierarchy Check)
    # Ελέγχουμε αν οποιοδήποτε group του χρήστη ταιριάζει ή είναι παιδί των απαιτούμενων scopes
    for required in required_scopes:
        for user_group in user_groups:
            if user_group == required or user_group.startswith(f"{required}/"):
                return True

    return False
