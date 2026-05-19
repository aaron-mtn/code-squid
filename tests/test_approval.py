from core.approval import ApprovalPolicy, USER_DENIED_TOOL_ACTION


class FakePrompter:
    def __init__(self, approved: bool) -> None:
        self.approved = approved
        self.actions = []

    def approve_action(self, action: dict) -> bool:
        self.actions.append(action)
        return self.approved


def test_approval_policy_never_approves_without_prompter() -> None:
    decision = ApprovalPolicy("never").check({"tool": "read_file"})

    assert decision.approved is True
    assert decision.reason == ""


def test_approval_policy_always_approves_when_prompter_approves() -> None:
    action = {"tool": "read_file"}
    prompter = FakePrompter(approved=True)

    decision = ApprovalPolicy("always", prompter=prompter).check(action)

    assert decision.approved is True
    assert decision.reason == ""
    assert prompter.actions == [action]


def test_approval_policy_always_denies_when_prompter_denies() -> None:
    action = {"tool": "read_file"}
    prompter = FakePrompter(approved=False)

    decision = ApprovalPolicy("always", prompter=prompter).check(action)

    assert decision.approved is False
    assert decision.reason == USER_DENIED_TOOL_ACTION
    assert prompter.actions == [action]
