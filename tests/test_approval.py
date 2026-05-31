from core.approval import ApprovalDecision, ApprovalPolicy, USER_DENIED_TOOL_ACTION


class FakePrompter:
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.actions = []

    def approve_action(self, action: dict) -> ApprovalDecision:
        self.actions.append(action)
        return self.decision


def test_approval_policy_never_approves_without_prompter() -> None:
    decision = ApprovalPolicy("never").check({"tool": "read_file"})

    assert decision.approved is True
    assert decision.reason == ""


def test_approval_policy_always_approves_when_prompter_approves() -> None:
    action = {"tool": "read_file"}
    prompter = FakePrompter(ApprovalDecision(approved=True))

    decision = ApprovalPolicy("always", prompter=prompter).check(action)

    assert decision.approved is True
    assert decision.reason == ""
    assert prompter.actions == [action]


def test_approval_policy_always_denies_when_prompter_denies() -> None:
    action = {"tool": "read_file"}
    prompter = FakePrompter(ApprovalDecision(approved=False))

    decision = ApprovalPolicy("always", prompter=prompter).check(action)

    assert decision.approved is False
    assert decision.reason == USER_DENIED_TOOL_ACTION
    assert decision.instruction == ""
    assert prompter.actions == [action]


def test_approval_policy_preserves_denial_instruction() -> None:
    action = {"tool": "run_command"}
    prompter = FakePrompter(
        ApprovalDecision(approved=False, instruction="Use pathlib instead")
    )

    decision = ApprovalPolicy("always", prompter=prompter).check(action)

    assert decision.approved is False
    assert decision.reason == USER_DENIED_TOOL_ACTION
    assert decision.instruction == "Use pathlib instead"
    assert prompter.actions == [action]
