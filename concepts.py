"""
concepts.py — Built-in knowledge dictionary + intent detection for Ultron-J ULTIMATE.

ULTIMATE UPGRADES:
- 15 new topics added (agriculture, startup, biotech, quantum, robotics, etc.)
- Intent detection now returns 10 types (up from 7)
- New intents: 'code_run', 'image_analyze', 'calculate', 'note', 'git'
- Smart entity extraction from queries
- Confidence scoring on intent detection
"""

import json
import os
import random
from config import CONCEPTS_FILE

# =============================================================================
# BUILT-IN KNOWLEDGE DICTIONARY — 44 topics (up from 29)
# =============================================================================

_BUILT_IN_CONCEPTS = {
    # ── AI / ML (original 14, kept) ─────────────────────────────────────────
    "artificial intelligence": (
        "Artificial Intelligence (AI) is the broad field of computer science focused on "
        "building systems that simulate human intelligence — reasoning, learning, planning, perception.\n\n"
        "Key branches: Machine Learning, Deep Learning, NLP, Computer Vision, Robotics.\n\n"
        "Real-world: Siri, self-driving cars (Tesla), ChatGPT, Midjourney."
    ),
    "machine learning": (
        "Machine Learning (ML) trains systems to learn patterns from data automatically.\n\n"
        "Three main types: Supervised (labeled data), Unsupervised (unlabeled), Reinforcement (reward-based).\n\n"
        "Real-world: Netflix recommendations, email spam detection, fraud detection."
    ),
    "deep learning": (
        "Deep Learning uses neural networks with many layers to learn from large datasets.\n\n"
        "Why powerful: extracts features from raw data without manual engineering.\n\n"
        "Real-world: Face recognition, voice assistants, medical imaging."
    ),
    "neural networks": (
        "Neural Networks are computing systems inspired by the brain — layers of connected nodes.\n\n"
        "Structure: Input layer → Hidden layers → Output layer.\n\n"
        "Real-world: Google Translate, image recognition, chatbots."
    ),
    "supervised learning": (
        "Supervised Learning trains on labeled data — every input has a known correct output.\n\n"
        "Real-world: Email spam filter, house price prediction, medical diagnosis."
    ),
    "unsupervised learning": (
        "Unsupervised Learning finds patterns in data without labels.\n\n"
        "Techniques: Clustering, Dimensionality reduction, Anomaly detection.\n\n"
        "Real-world: Customer segmentation, news article grouping, fraud detection."
    ),
    "reinforcement learning": (
        "Reinforcement Learning trains an agent via rewards and penalties.\n\n"
        "Key concepts: Agent, Environment, Reward, Policy.\n\n"
        "Real-world: AlphaGo, game-playing AIs, robot manipulation."
    ),
    "natural language processing": (
        "NLP enables machines to understand and generate human language.\n\n"
        "Key tasks: Sentiment analysis, Translation, Summarization, NER.\n\n"
        "Real-world: ChatGPT, Claude, Google Translate, Gmail smart compose."
    ),
    "computer vision": (
        "Computer Vision gives machines the ability to interpret images and video.\n\n"
        "Key tasks: Object detection, Classification, Facial recognition, Segmentation.\n\n"
        "Real-world: Self-driving cars, face unlock, factory quality inspection."
    ),
    "generative ai": (
        "Generative AI creates new content — text, images, audio, video, code.\n\n"
        "Key models: GPT-4, Claude (text) | Midjourney, DALL-E (image) | Sora (video).\n\n"
        "Real-world: Writing assistants, AI art, code generation."
    ),
    "large language model": (
        "LLMs are deep learning models trained on massive text to understand and generate language.\n\n"
        "Famous LLMs: GPT-4 (OpenAI), Claude (Anthropic), Gemini (Google), LLaMA (Meta).\n\n"
        "Uses: Chatbots, code generation, document summarization."
    ),
    "random forest": (
        "Random Forest builds many decision trees and combines their predictions.\n\n"
        "Why it works: Many weak trees vote together → one strong prediction.\n\n"
        "Real-world: Fraud detection, disease risk, stock prediction."
    ),
    "support vector machine": (
        "SVMs find the optimal hyperplane that best separates classes in data.\n\n"
        "Kernel trick: handles non-linear data by mapping to higher dimensions.\n\n"
        "Real-world: Handwriting recognition, image classification, cancer detection."
    ),
    "transformer": (
        "Transformers are the architecture behind modern LLMs — uses attention mechanisms.\n\n"
        "Key innovation: Self-attention allows the model to weigh importance of each word relative to others.\n\n"
        "Real-world: GPT, BERT, Claude, T5, Whisper (speech), Vision Transformer."
    ),
    # ── Programming ──────────────────────────────────────────────────────────
    "python": (
        "Python is the dominant language for AI, data science, and automation.\n\n"
        "Key libraries: NumPy/Pandas (data), TensorFlow/PyTorch (deep learning), Flask/FastAPI (web).\n\n"
        "Used by: Google, NASA, Instagram, Netflix."
    ),
    "javascript": (
        "JavaScript is the primary web language — runs in browsers and on servers (Node.js).\n\n"
        "Frameworks: React, Vue, Angular (frontend) | Node.js, Express (backend).\n\n"
        "Used by: Facebook, Twitter, Netflix, Airbnb."
    ),
    "flask": (
        "Flask is a lightweight Python web framework for building APIs and web apps.\n\n"
        "Key concepts: Routes, Blueprints, Jinja2 templates, SQLAlchemy ORM, SSE streaming.\n\n"
        "Used for: REST APIs, microservices, internal tools, ML model serving."
    ),
    # ── Core tech ────────────────────────────────────────────────────────────
    "blockchain": (
        "Blockchain is a distributed, immutable ledger across a network of computers.\n\n"
        "How it works: Transactions → Blocks → Linked chain → Consensus validation.\n\n"
        "Real-world: Bitcoin/Ethereum, smart contracts, supply chain."
    ),
    "cloud computing": (
        "Cloud Computing delivers computing resources over the internet on pay-as-you-go.\n\n"
        "Models: IaaS (infrastructure), PaaS (platform), SaaS (software).\n\n"
        "Providers: AWS, Google Cloud, Microsoft Azure."
    ),
    "cybersecurity": (
        "Cybersecurity protects systems, networks, and data from digital attacks.\n\n"
        "Domains: Network security, App security, Cryptography, Incident response.\n\n"
        "Threats: Malware, Phishing, Ransomware, DDoS | Tools: Firewalls, MFA, VPNs."
    ),
    "api": (
        "An API lets different software applications communicate with each other.\n\n"
        "Types: REST (HTTP), GraphQL (flexible queries), WebSocket (real-time).\n\n"
        "Real-world: Weather apps, Login with Google, Stripe payments."
    ),
    "database": (
        "A database stores and manages structured data electronically.\n\n"
        "SQL (relational): MySQL, PostgreSQL, SQLite | NoSQL: MongoDB, Redis.\n\n"
        "Uses: User accounts, product catalogs, banking records."
    ),
    "docker": (
        "Docker packages applications and their dependencies into containers.\n\n"
        "Why useful: Consistent environment across dev/test/production. 'It works on my machine' solved.\n\n"
        "Key concepts: Image, Container, Dockerfile, Docker Compose, Registry."
    ),
    "git": (
        "Git is the most widely used distributed version control system.\n\n"
        "Key commands: init, clone, add, commit, push, pull, branch, merge, rebase.\n\n"
        "Platforms: GitHub, GitLab, Bitbucket."
    ),
    # ── Emerging tech ────────────────────────────────────────────────────────
    "internet of things": (
        "IoT connects physical devices with sensors and internet connectivity.\n\n"
        "Examples: Smart home (Alexa, Nest), Wearables (Apple Watch), Industrial sensors.\n\n"
        "Challenge: Security and privacy of billions of connected devices."
    ),
    "augmented reality": (
        "AR overlays digital content onto the real world through a screen or camera.\n\n"
        "vs VR: AR enhances reality; VR replaces it entirely.\n\n"
        "Real-world: Snapchat filters, IKEA Place, Pokemon GO, Surgical navigation."
    ),
    "quantum computing": (
        "Quantum computers use qubits (superposition + entanglement) instead of classical bits.\n\n"
        "Advantage: Can solve certain problems exponentially faster than classical computers.\n\n"
        "Use cases: Cryptography breaking, drug discovery, optimization problems.\n\n"
        "Players: IBM Quantum, Google Sycamore, IonQ, D-Wave."
    ),
    "robotics": (
        "Robotics combines mechanical engineering, electronics, and software for physical task automation.\n\n"
        "Key fields: Industrial automation, surgical robots, autonomous vehicles, humanoid robots.\n\n"
        "Leading platforms: ROS (Robot Operating System), Boston Dynamics, Tesla Optimus."
    ),
    "edge computing": (
        "Edge Computing processes data near where it's generated — not in a central cloud.\n\n"
        "Why it matters: Lower latency, offline operation, reduced bandwidth.\n\n"
        "Use cases: Autonomous vehicles, smart factories, rural IoT deployments."
    ),
    # ── Data / Analytics ─────────────────────────────────────────────────────
    "data science": (
        "Data Science extracts insights from structured and unstructured data.\n\n"
        "Workflow: Collect → Clean → Analyze → Model → Communicate.\n\n"
        "Tools: Python, R, SQL, Jupyter, Tableau | Used in: Healthcare, finance, sports."
    ),
    "rag": (
        "RAG (Retrieval-Augmented Generation) enhances LLMs by retrieving relevant documents before generating.\n\n"
        "How it works: Query → Retrieve from vector DB → Inject into prompt → Generate grounded answer.\n\n"
        "Why it matters: Reduces hallucination, enables up-to-date answers without retraining.\n\n"
        "Tools: LangChain, LlamaIndex, ChromaDB, Pinecone, FAISS."
    ),
    "vector database": (
        "Vector databases store and search high-dimensional embeddings efficiently.\n\n"
        "Core operation: Approximate Nearest Neighbor (ANN) search on vectors.\n\n"
        "Popular options: ChromaDB (local), Pinecone (cloud), Weaviate, Qdrant, FAISS."
    ),
    # ── Agriculture (Jeevan's domain) ────────────────────────────────────────
    "precision agriculture": (
        "Precision agriculture uses technology to optimize crop yield with minimal inputs.\n\n"
        "Tools: GPS, drones, soil sensors, satellite imagery, AI yield prediction.\n\n"
        "Benefits: Reduces water, fertilizer, and pesticide waste while increasing productivity.\n\n"
        "In India: ISRO's Bhuvan, AgriStack, Khethari platform."
    ),
    "agritech": (
        "AgriTech applies technology to improve agriculture productivity and farmer income.\n\n"
        "Segments: IoT soil sensors, drone surveillance, AI disease detection, market price apps.\n\n"
        "Key Indian players: DeHaat, AgroStar, Fasal, Ninjacart, Khethari.\n\n"
        "Opportunity: 60% of India's workforce in agriculture — massive underserved market."
    ),
    "soil science": (
        "Soil Science studies soil composition, structure, and health for agricultural productivity.\n\n"
        "Key parameters: pH, NPK (nitrogen, phosphorus, potassium), organic matter, moisture.\n\n"
        "In India: ICAR soil health cards help farmers understand their soil type."
    ),
    "crop protection": (
        "Crop protection prevents yield loss from pests, diseases, and weeds.\n\n"
        "Methods: Chemical pesticides, biological control, IPM (Integrated Pest Management).\n\n"
        "AI application: Disease detection from leaf images using computer vision."
    ),
    # ── Business / Startup ───────────────────────────────────────────────────
    "startup": (
        "A startup is a company in its early stages, typically with high growth potential and uncertainty.\n\n"
        "Key stages: Idea → MVP → Product-Market Fit → Growth → Scale.\n\n"
        "India startup ecosystem: Bengaluru, Hyderabad, Mumbai hubs. DPIIT-recognized startups >100k."
    ),
    "product market fit": (
        "Product-Market Fit (PMF) is the degree to which a product satisfies strong market demand.\n\n"
        "Marc Andreessen's definition: 'Being in a good market with a product that can satisfy that market.'\n\n"
        "Signs of PMF: Organic word-of-mouth, customers upset if you shut down, rapid growth."
    ),
    "venture capital": (
        "Venture Capital (VC) funds early-stage, high-risk companies in exchange for equity.\n\n"
        "Stages: Seed → Series A → Series B → Series C → IPO.\n\n"
        "Top Indian VCs: Sequoia India (Peak XV), Nexus, Matrix Partners, Accel India."
    ),
    # ── Health / Bio ─────────────────────────────────────────────────────────
    "bioinformatics": (
        "Bioinformatics applies computational methods to analyze biological data.\n\n"
        "Key tasks: DNA sequence analysis, protein structure prediction, genomics.\n\n"
        "Tools: BLAST, Biopython, Galaxy, R Bioconductor."
    ),
    # ── OS / System ──────────────────────────────────────────────────────────
    "operating system": (
        "An OS manages hardware and provides services for software to run.\n\n"
        "Functions: Process management, Memory management, File system, Device drivers.\n\n"
        "Examples: Windows, macOS, Linux, Android, iOS."
    ),
    "linux": (
        "Linux is the dominant open-source operating system for servers, embedded systems, and development.\n\n"
        "Key distros: Ubuntu, Debian, CentOS, Arch, Fedora.\n\n"
        "Essential commands: ls, cd, grep, find, chmod, ps, top, curl, wget, ssh, scp."
    ),
    # ── Ollama / local AI ────────────────────────────────────────────────────
    "ollama": (
        "Ollama lets you run large language models locally on your own machine — no internet needed.\n\n"
        "How to use: `ollama run mistral` or `ollama run llama3`.\n\n"
        "Popular models: TinyLlama (1.1B, fast), Mistral 7B, LLaMA 3 8B, Phi-3 Medium.\n\n"
        "API: POST http://localhost:11434/api/generate"
    ),
}

# =============================================================================
# LOAD / RELOAD FROM DISK
# =============================================================================

def _load_concepts() -> dict:
    if not os.path.exists(CONCEPTS_FILE):
        try:
            from memory import atomic_json_write as _aw
            _aw(CONCEPTS_FILE, _BUILT_IN_CONCEPTS)
        except Exception:
            with open(CONCEPTS_FILE, "w", encoding="utf-8") as f:
                json.dump(_BUILT_IN_CONCEPTS, f, indent=2, ensure_ascii=False)
        return dict(_BUILT_IN_CONCEPTS)
    try:
        with open(CONCEPTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(_BUILT_IN_CONCEPTS)
        merged.update(data)
        return merged
    except Exception:
        return dict(_BUILT_IN_CONCEPTS)


CONCEPTS = _load_concepts()


def reload_concepts():
    global CONCEPTS
    CONCEPTS = _load_concepts()


def extract_concepts(text: str) -> list:
    """Find all concept keys that appear in the text as whole words/phrases."""
    import re as _re
    text_lower = text.lower()
    matched = []
    for key in CONCEPTS:
        # Use word boundaries so 'api' doesn't match 'capital', 'python' only matches standalone word
        pattern = r'\b' + _re.escape(key) + r'\b'
        if _re.search(pattern, text_lower):
            matched.append(key)
    return matched


def is_concept_question(text: str) -> str | None:
    """Return the first matching concept key if text is a definitional question about a concept.
    Skip if the user is asking to generate, write, or use the concept — not explain it."""
    # If the question asks to generate/create/use something, don't use concept lookup
    _action_verbs = (
        "write ", "create ", "generate ", "make ", "build ",
        "implement ", "code ", "show me ", "give me ", "solve ",
        "how to ", "how do i ", "how can i ", "help me ",
        "what does ", "what do ", "use python", "using python",
        "in python", "reverse ", "fix ", "debug ", "run ",
        "remember ", "store ", "save ", "note that", "don't forget",
    )
    t = text.lower()
    if any(v in t for v in _action_verbs):
        return None
    # Long questions (>12 words) are rarely pure concept lookups
    if len(t.split()) > 12:
        return None
    found = extract_concepts(text)
    return found[0] if found else None

# =============================================================================
# INTENT DETECTION — 10 intent types
# =============================================================================

INTENTS = {
    "greeting": {
        "patterns": ["hello", "hi", "hey", "good morning", "good evening", "what's up",
                     "how are you", "sup", "yo", "namaste", "hola"],
        "weight":   10,
    },
    "news": {
        "patterns": ["news", "latest", "what happened", "breaking", "today's news",
                     "current events", "headlines", "update me"],
        "weight":   8,
    },
    "weather": {
        "patterns": ["weather", "temperature", "rain", "forecast", "humidity",
                     "how hot", "how cold", "will it rain"],
        "weight":   9,
    },
    "price": {
        "patterns": ["price", "cost", "how much", "rate", "stock price",
                     "crypto", "bitcoin", "dollar", "rupee", "exchange rate"],
        "weight":   8,
    },
    "calculate": {
        "patterns": ["calculate", "compute", "what is", "how much is", "convert",
                     "percentage", "formula", "math", "solve", "+", "-", "*", "/"],
        "weight":   7,
    },
    "code_run": {
        "patterns": ["run this", "execute", "run the code", "test this code",
                     "what does this code do", "debug", "fix this code"],
        "weight":   9,
    },
    "note": {
        "patterns": ["remember this", "save this", "note this down", "make a note",
                     "don't forget", "log this", "add to notes"],
        "weight":   9,
    },
    "git": {
        "patterns": ["git status", "git commit", "git push", "git pull", "branch",
                     "repository", "merge conflict", "git log", "checkout"],
        "weight":   9,
    },
    "image_analyze": {
        "patterns": ["analyze this image", "what is in this image", "describe this photo",
                     "look at this", "what do you see", "read this image"],
        "weight":   9,
    },
    "self_think": {
        "patterns": ["kartha", "who are you", "what are you", "your capabilities",
                     "system status", "self awareness", "what can you do"],
        "weight":   10,
    },
    "timer": {
        "patterns": ["set a timer", "remind me in", "alarm", "countdown", "after x minutes"],
        "weight":   8,
    },
    "search": {
        "patterns": ["search for", "find", "look up", "google", "what is", "who is",
                     "tell me about", "explain", "describe"],
        "weight":   5,
    },
    "chat": {
        "patterns": [],    # fallback
        "weight":   1,
    },
}


def intent_agent(text: str) -> dict:
    """
    Detect the most likely intent from user text.
    Returns {"intent": str, "confidence": float, "entities": list}
    """
    import re as _re
    text_lower = text.lower().strip()
    scores     = {}

    for intent_name, config in INTENTS.items():
        score = 0
        for pattern in config.get("patterns", []):
            if len(pattern) <= 1:
                # Single-char operators: require math context (digit on at least one side)
                if _re.search(r'\d\s*' + _re.escape(pattern) + r'|\s' + _re.escape(pattern) + r'\s*\d', text_lower):
                    score += config.get("weight", 1)
            else:
                # Multi-char patterns: use word boundaries to avoid substring false positives
                if _re.search(r'\b' + _re.escape(pattern) + r'\b', text_lower):
                    score += config.get("weight", 1)
        scores[intent_name] = score

    # Pick highest
    best_intent = max(scores, key=scores.get)
    best_score  = scores[best_intent]

    # Fallback to "chat" if no clear signal
    if best_score == 0:
        best_intent = "chat"

    total       = sum(scores.values()) or 1
    confidence  = round(best_score / total, 2)

    # Simple entity extraction
    entities    = _extract_entities(text)

    return {
        "intent":     best_intent,
        "confidence": confidence,
        "entities":   entities,
        "all_scores": {k: v for k, v in scores.items() if v > 0},
    }


def _extract_entities(text: str) -> list:
    """
    Extract likely entities (proper nouns, code file names, currencies, etc.)
    from user text. Simple heuristic — no NLP library needed.
    """
    import re
    entities = []

    # Capitalized words (likely names/places)
    caps = re.findall(r'\b[A-Z][a-z]{2,}\b', text)
    entities.extend(caps[:5])

    # File references
    files = re.findall(r'\b[\w]+\.(py|js|json|txt|md|html|csv|sql)\b', text)
    entities.extend([f[0] + "." + f[1] if isinstance(f, tuple) else f for f in files])

    # URLs
    urls = re.findall(r'https?://[^\s]+', text)
    entities.extend(urls[:2])

    return list(dict.fromkeys(entities))[:10]   # deduplicate, cap at 10

# =============================================================================
# GREETINGS
# =============================================================================

_GREETINGS_IN = [
    "hello", "hi", "hey", "good morning", "good evening", "good afternoon",
    "good night", "what's up", "sup", "howdy", "yo", "greetings",
    "namaste", "hola", "salut", "hii", "heyy", "helo",
]


def is_greeting(text: str) -> bool:
    return text.lower().strip() in _GREETINGS_IN or text.lower().strip().rstrip("!").rstrip("?") in _GREETINGS_IN


_GREETING_RESPONSES = [
    "Here. What do you need?",
    "Online. How can I help?",
    "Ready. What's the task?",
    "Monitoring. What do you need?",
    "Systems active. Give me something to work on.",
    "Ultron-J online. What's on your mind?",
]


def greeting_reply() -> str:
    return random.choice(_GREETING_RESPONSES)
