"""
smart_clarifier.py — Ultron's Intent Router
============================================
FIXED: Only asks for source selection when user EXPLICITLY wants to browse
somewhere. Conversational questions, explanations, general knowledge —
all go straight to Ultron's brain. No more annoying source pickers for
"tell me about yourself" or "what is Python".
"""

import re
import os
from typing import Dict, List, Optional, Any

# =============================================================================
# SOURCE DEFINITIONS
# =============================================================================

SOURCES = {
    "claude":       {"label": "Let Ultron Answer",    "url": "self",                                                  "icon": "🤖", "type": "ai",       "best_for": ["everything"]},
    "youtube":      {"label": "YouTube",              "url": "https://www.youtube.com/results?search_query={query}",  "icon": "▶️", "type": "video",    "best_for": ["tutorials", "videos"]},
    "google":       {"label": "Google Search",        "url": "https://www.google.com/search?q={query}",               "icon": "🔍", "type": "search",   "best_for": ["general search"]},
    "google_news":  {"label": "Google News",          "url": "https://news.google.com/search?q={query}",              "icon": "📰", "type": "news",     "best_for": ["news", "current events"]},
    "reddit":       {"label": "Reddit",               "url": "https://www.reddit.com/search/?q={query}",              "icon": "👽", "type": "social",   "best_for": ["opinions", "community"]},
    "github":       {"label": "GitHub",               "url": "https://github.com/search?q={query}",                   "icon": "💻", "type": "code",     "best_for": ["code", "open source"]},
    "stackoverflow":{"label": "StackOverflow",        "url": "https://stackoverflow.com/search?q={query}",            "icon": "📚", "type": "code",     "best_for": ["coding errors", "debug"]},
    "wikipedia":    {"label": "Wikipedia",            "url": "https://en.wikipedia.org/wiki/Special:Search?search={query}", "icon": "📖", "type": "knowledge", "best_for": ["facts", "history"]},
    "amazon":       {"label": "Amazon India",         "url": "https://www.amazon.in/s?k={query}",                     "icon": "🛒", "type": "shop",     "best_for": ["buy", "shop", "products"]},
    "flipkart":     {"label": "Flipkart",             "url": "https://www.flipkart.com/search?q={query}",             "icon": "🛍️","type": "shop",     "best_for": ["buy India", "deals"]},
    "maps":         {"label": "Google Maps",          "url": "https://www.google.com/maps/search/{query}",            "icon": "🗺️","type": "map",      "best_for": ["location", "nearby", "directions"]},
    "local_files":  {"label": "My Local Files",       "url": "LOCAL",                                                 "icon": "📁", "type": "local",    "best_for": ["my files", "documents"]},
}

# =============================================================================
# CLARIFYING FLOWS — only for explicit external search requests
# =============================================================================

CLARIFYING_FLOWS = {
    "buy_search": {
        "condition": lambda q, i: any(t in q.lower() for t in ["buy", "purchase", "order", "price of", "cost of", "how much is"]),
        "question": "Where would you like to shop?",
        "options": [
            {"key": "self",     "label": "Ask Ultron",       "icon": "🤖", "sources": ["claude"]},
            {"key": "amazon",   "label": "Amazon India",     "icon": "🛒", "sources": ["amazon"]},
            {"key": "flipkart", "label": "Flipkart",         "icon": "🛍️","sources": ["flipkart"]},
            {"key": "google",   "label": "Google Shopping",  "icon": "🔍", "sources": ["google"]},
        ],
    },
    "video_search": {
        "condition": lambda q, i: any(t in q.lower() for t in ["search on youtube", "find on youtube", "youtube video", "watch tutorial on", "video about"]),
        "question": "Want a video tutorial or a written explanation?",
        "options": [
            {"key": "self",    "label": "Ask Ultron",        "icon": "🤖", "sources": ["claude"]},
            {"key": "youtube", "label": "YouTube Video",     "icon": "▶️", "sources": ["youtube"]},
            {"key": "google",  "label": "Google Search",     "icon": "🔍", "sources": ["google"]},
        ],
    },
    "news_search": {
        "condition": lambda q, i: any(t in q.lower() for t in ["search news", "find news", "latest news on", "news about"]),
        "question": "Where should I find the news?",
        "options": [
            {"key": "self",        "label": "Ask Ultron",    "icon": "🤖", "sources": ["claude"]},
            {"key": "google_news", "label": "Google News",   "icon": "📰", "sources": ["google_news"]},
            {"key": "reddit",      "label": "Reddit",        "icon": "👽", "sources": ["reddit"]},
        ],
    },
    "location_search": {
        "condition": lambda q, i: any(t in q.lower() for t in ["find on maps", "search on maps", "where is", "directions to", "near me", "nearby"]),
        "question": "Want to open this in Maps?",
        "options": [
            {"key": "maps",   "label": "Open in Maps",       "icon": "🗺️","sources": ["maps"]},
            {"key": "self",   "label": "Ask Ultron",         "icon": "🤖", "sources": ["claude"]},
            {"key": "google", "label": "Google Search",      "icon": "🔍", "sources": ["google"]},
        ],
    },
    "generic_search": {
        "condition": lambda q, i: True,
        "question": "Where would you like to search?",
        "options": [
            {"key": "self",    "label": "Ask Ultron",        "icon": "🤖", "sources": ["claude"]},
            {"key": "google",  "label": "Google",            "icon": "🔍", "sources": ["google"]},
            {"key": "youtube", "label": "YouTube",           "icon": "▶️", "sources": ["youtube"]},
            {"key": "reddit",  "label": "Reddit",            "icon": "👽", "sources": ["reddit"]},
        ],
    },
}

# =============================================================================
# INTENT SIGNALS
# =============================================================================

INTENT_SIGNALS = {
    "want_video":    ["how to", "tutorial", "show me", "watch", "video", "step by step"],
    "want_code":     ["code", "script", "program", "implement", "build", "develop", "function", "algorithm", "github"],
    "want_news":     ["latest news", "news about", "breaking", "headlines", "current events"],
    "want_shopping": ["buy", "price", "order", "cost", "purchase", "shop", "amazon", "flipkart", "deal"],
    "want_place":    ["near me", "nearby", "location", "direction", "where is", "how to get to", "restaurant", "hotel"],
    "want_video_platform": ["search on youtube", "find on youtube", "video about", "watch tutorial"],
    "want_news_platform":  ["search news", "find news", "latest news on", "news about"],
    "want_external": ["search for", "find me", "look up", "search on", "find on", "look on", "open google", "open youtube"],
}


def detect_intent_signals(query: str) -> List[str]:
    ql = query.lower()
    found = []
    for intent, keywords in INTENT_SIGNALS.items():
        if any(k in ql for k in keywords):
            found.append(intent)
    return found


# =============================================================================
# CLARIFICATION ENGINE
# =============================================================================

class ClarificationEngine:
    """
    STRICT POLICY: Only ask for source clarification when user EXPLICITLY
    wants to browse/search an external platform. All other questions go
    directly to Ultron's LLM brain.
    """

    # Commands that NEVER need clarification
    IMMEDIATE_ACTIONS = [
        "take screenshot", "screenshot", "create folder", "open folder",
        "volume up", "volume down", "mute", "lock screen", "sleep",
        "open vs code", "open notepad", "open calculator",
        "what time", "what date", "what day",
        "open chrome", "open browser",
        "phone screenshot", "is my phone",
        "save the code", "run the code", "run project",
        "play music", "pause", "next song",
    ]

    # Phrases that should ALWAYS go straight to Ultron — never ask for source
    DIRECT_TO_ULTRON = [
        # Identity / conversational
        "who are you", "what are you", "tell me about yourself", "introduce yourself",
        "what can you do", "what do you do", "your name", "are you", "do you",
        # Greetings
        "hello", "hi ", "hey ", "good morning", "good evening", "good night",
        "how are you", "sup ", "what's up", "wassup",
        # Explanations (Ultron can answer these directly)
        "what is ", "what are ", "explain ", "describe ",
        "how does ", "how do ", "why is ", "why does ", "why are ",
        "what happens ", "what happened ", "when did ", "when was ", "when is ",
        "who is ", "who was ", "who are ",
        "difference between", "compare ", "versus ", "vs ",
        # Requests Ultron can handle
        "write ", "create ", "make ", "generate ", "give me ", "show me how",
        "help me ", "i need help", "can you ", "could you ", "will you ",
        "summarize ", "analyze ", "review ", "suggest ", "recommend ",
        "calculate ", "compute ", "solve ", "what is the result of",
        "remind me", "remember ", "tell me a ", "tell me about ",
        "translate ", "convert ",
        # Personal
        "i am ", "i'm ", "my ", "i want ", "i need ", "i think ",
        "i feel ", "i have ", "i was ",
        # Acknowledgements
        "thank", "thanks", "ok ", "okay", "sure", "great", "nice", "cool",
        "awesome", "perfect", "understood", "got it",
        # Time/date
        "what time", "what day", "what date", "current time", "today",
        # Weather, system
        "weather", "temperature", "system health", "how's my computer",
        # Facts/knowledge Ultron knows
        "tell me", "fact about", "history of", "origin of",
        "definition of", "meaning of",
    ]

    # ONLY these explicit patterns trigger source selection
    EXPLICIT_EXTERNAL_SEARCH = [
        "search for ",
        "search on ",
        "find on ",
        "look on ",
        "buy ",
        "purchase ",
        "order from ",
        "shop for ",
        "find me a product",
        "near me",
        "nearby ",
        "directions to ",
        "search youtube for ",
        "find youtube ",
        "youtube search ",
        "open maps",
        "google maps",
        "search reddit",
        "find on reddit",
        "search github",
        "find on github",
        "news about ",
        "latest news on ",
        "search news",
    ]

    def needs_clarification(self, query: str) -> bool:
        """
        Returns True ONLY when user explicitly wants to search an external platform.
        This should be RARE — most questions go straight to Ultron.
        """
        ql = query.lower().strip()

        # Never ask for very short queries
        if len(query.split()) <= 4:
            return False

        # Never ask for immediate computer actions
        for action in self.IMMEDIATE_ACTIONS:
            if action in ql:
                return False

        # Never ask if any of these patterns match — Ultron handles directly
        for pattern in self.DIRECT_TO_ULTRON:
            if ql.startswith(pattern) or (" " + pattern) in ql or ql == pattern.strip():
                return False

        # Only ask if user is EXPLICITLY requesting an external search/browse
        for trigger in self.EXPLICIT_EXTERNAL_SEARCH:
            if trigger in ql:
                return True

        # Default: NO — let Ultron answer
        return False

    def get_clarification(self, query: str) -> Optional[Dict]:
        if not self.needs_clarification(query):
            return None

        intents = detect_intent_signals(query)

        for flow_key, flow in CLARIFYING_FLOWS.items():
            if flow_key == "generic_search":
                continue
            try:
                if flow["condition"](query, intents):
                    return {
                        "flow":     flow_key,
                        "question": flow["question"],
                        "options":  flow["options"],
                        "query":    query,
                        "intents":  intents,
                    }
            except Exception:
                continue

        return {
            "flow":     "generic_search",
            "question": CLARIFYING_FLOWS["generic_search"]["question"],
            "options":  CLARIFYING_FLOWS["generic_search"]["options"],
            "query":    query,
            "intents":  intents,
        }

    def execute_with_source(self, query: str, source_key: str) -> Dict:
        import webbrowser, subprocess
        from pathlib import Path

        if source_key == "self" or source_key == "claude":
            return {"action": "self_answer", "query": query}

        if source_key not in SOURCES:
            return {"action": "error", "message": f"Unknown source: {source_key}"}

        source = SOURCES[source_key]
        url    = source["url"]

        if url == "LOCAL":
            docs = str(Path.home() / "Documents")
            subprocess.Popen(f'explorer "{docs}"', shell=True)
            return {"action": "opened_local", "message": f"Opening Documents. Search for: {query}", "source": source["label"]}

        if url == "WORKSPACE":
            ws = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
            os.makedirs(ws, exist_ok=True)
            subprocess.Popen(f'explorer "{ws}"', shell=True)
            return {"action": "opened_workspace", "message": "Opening Ultron workspace.", "source": source["label"]}

        qe = query.replace(" ", "+")
        qt = query.replace(" ", "")
        final_url = url.replace("{query}", qe).replace("{query_tag}", qt)
        webbrowser.open(final_url)
        return {
            "action":  "opened_browser",
            "message": f"Opening {source['label']} for: {query}",
            "url":     final_url,
            "source":  source["label"],
            "icon":    source.get("icon", "🔍"),
        }


_engine = ClarificationEngine()


def check_clarification(query: str) -> Optional[Dict]:
    return _engine.get_clarification(query)


def execute_with_choice(query: str, source_key: str) -> Dict:
    return _engine.execute_with_source(query, source_key)


def get_all_sources() -> Dict:
    return SOURCES
