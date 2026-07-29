"""Is this a question wanting an answer, or a command wanting an action?

The action orchestrator's LLM picker maps info-shaped questions onto
`search_web`, and both chat routes then treat the action's output as the final
reply. For a real command that is correct. For "what is the price of gold" it
means the raw scraped page is handed back as the answer and the language model
never sees the question at all.

voice_routes has guarded against this since the search_web hijack was first
found; app.py had no equivalent, which is why the same question behaved
differently depending on whether it was typed or spoken. Keeping the rule here
means the two routes cannot drift apart again.
"""

# Prefixes that open a request for information. A question mark is not enough
# on its own — "can you open chrome?" is still a command.
INFO_LEADS = (
    "who is", "who's", "who are", "what is", "what's", "whats", "what are",
    "when is", "when's", "when did", "when was", "where is", "where's",
    "where are", "why is", "why does", "why did", "how is", "how does",
    "how did", "how do", "how can", "how much", "how many", "which is",
    "tell me about", "tell me", "do you know", "can you tell", "explain",
)


def is_info_question(text) -> bool:
    """True when `text` asks for information rather than an action.

    Matched as a PREFIX only. "open the file and tell me what is inside" is a
    command that happens to contain a lead-in, and must still reach the
    orchestrator.
    """
    try:
        s = " ".join(str(text or "").lower().split())
        if not s:
            return False
        return any(s == lead or s.startswith(lead + " ") for lead in INFO_LEADS)
    except Exception:
        return False
