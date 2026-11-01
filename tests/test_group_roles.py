import pytest

from atsig_common.auth.context import BaseAuthContext
from atsig_common.auth.groups import SUPER_GROUPS, validate_user_groups


def ctx(*groups: str) -> BaseAuthContext:
    return BaseAuthContext(
        sub="u", email="e@x.gr", groups=list(groups), given_name="", family_name=""
    )


@pytest.mark.parametrize(
    ("groups", "role"),
    [
        (["/Administrators"], "is_admin"),
        (["/Evaluators"], "is_evaluator"),
        (["/Applicants"], "is_applicant"),
        (["/Secretary/Program"], "is_program_secretary"),
        (["/Secretary/Department"], "is_department_secretary"),
        (["/Secretary/Program"], "is_secretary"),
        (["/Agents/Child"], "is_child_agent"),
        (["/Agents/Parent"], "is_parent_agent"),
        (["/Agents/Child"], "is_agent"),
    ],
)
def test_the_groups_of_the_realm_give_their_role(groups, role):
    assert getattr(ctx(*groups), role) is True


def test_roles_are_independent_for_a_user_with_several_groups():
    user = ctx("/Applicants", "/Evaluators")

    assert user.is_applicant and user.is_evaluator
    assert not user.is_admin and not user.is_secretary and not user.is_agent


@pytest.mark.parametrize(
    "group",
    ["/Applicants/Administrators", "/Other/Evaluators", "/Foo/Secretary/Program"],
)
def test_a_group_that_only_ends_with_the_same_text_gives_no_role(group):
    user = ctx(group)

    assert not user.is_admin
    assert not user.is_evaluator
    assert not user.is_secretary


def test_role_and_scope_check_agree():
    for group in ("/Applicants/Administrators", "/Administrators"):
        assert ctx(group).is_admin == validate_user_groups([group], SUPER_GROUPS)
