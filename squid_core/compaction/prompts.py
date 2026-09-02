"""Generic prompts for transcript compaction."""


COMPACTION_SYSTEM_PROMPT = (
    "You summarize prior agent interaction context for safe continuation."
)


def compaction_prompt(prior_context: str) -> str:
    return f"""
Summarize this prior interaction context so a later turn can continue safely.

Preserve the original and current task context, important findings, relevant files and resources, actions already taken, tool and command results, verification results, failed attempts and corrections, the current next step, and remaining concrete risks or unknowns.
Use exact paths and identifiers when available. Do not invent facts or add speculative risks.
Prefer recent results over older assumptions.
Do not include a title or top-level heading. Return only the summary body.

Prior context:
{prior_context}
""".strip()
