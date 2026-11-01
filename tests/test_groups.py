import pytest

from atsig_common.auth.groups import (
    MAIN_GROUPS,
    SUPER_GROUPS,
    GroupEnum,
    validate_user_groups,
)


def test_helpdesk_is_not_a_group_anymore():
    assert not hasattr(GroupEnum, "HELPDESK")
    assert "/Helpdesk" not in {group.value for group in GroupEnum}
    assert "/Helpdesk" not in SUPER_GROUPS + MAIN_GROUPS


def test_only_the_administrators_group_bypasses_the_scope_check():
    assert SUPER_GROUPS == ["/Administrators"]
    assert validate_user_groups(["/Administrators"], ["/Secretary"])
    assert not validate_user_groups(["/Helpdesk"], ["/Secretary"])
    assert not validate_user_groups(["/Helpdesk"], SUPER_GROUPS)


@pytest.mark.parametrize(
    ("user_groups", "required", "allowed"),
    [
        (["/Secretary/Program"], ["/Secretary"], True),  # a child group counts
        (["/Secretary/Program"], ["/Secretary/Program"], True),
        (["/Secretary/Department"], ["/Secretary/Program"], False),
        (["/Applicants"], ["/Secretary"], False),
        (["/Applicants"], [], True),  # no scope required: any logged-in user
    ],
)
def test_the_scope_check_is_unchanged_for_everyone_else(user_groups, required, allowed):
    assert validate_user_groups(user_groups, required) is allowed
