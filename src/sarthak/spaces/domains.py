"""
Sarthak Spaces — Domain knowledge registry.

Concept trees, tools, and workspace templates for every domain.
Agents use this without LLM calls — LLMs only ENRICH within this structure.

Adding a new domain:
1. Define CONCEPT_TREE (SkillLevel → list[str])
2. Define TOOLS (list[ToolRecommendation])
3. Register in DOMAIN_REGISTRY
"""
from __future__ import annotations

from sarthak.spaces.models import SkillLevel, SpaceType, ToolRecommendation

# ── Tool builder helper ────────────────────────────────────────────────────────

def _tool(
    name: str, purpose: str, *,
    linux: str, mac: str = "", win: str = "",
    url: str = "", why: str = "", category: str = "core",
) -> ToolRecommendation:
    return ToolRecommendation(
        name=name, purpose=purpose,
        install_linux=linux,
        install_mac=mac or linux,
        install_windows=win or linux,
        url=url, why_experts_use_it=why, category=category,
    )


# ══════════════════════════════════════════════════════════════════════════════
# DATA SCIENCE / AI ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

DS_AI_CONCEPT_TREE: dict[SkillLevel, list[str]] = {
    SkillLevel.NOVICE: [
        "Python basics: lists, dicts, functions, comprehensions",
        "NumPy arrays and vectorized math",
        "Pandas: DataFrames, groupby, merge",
        "Matplotlib & Seaborn: visualizing distributions and relationships",
        "Statistics: mean, variance, standard deviation, distributions",
        "Probability: events, Bayes theorem, conditional probability",
    ],
    SkillLevel.BEGINNER: [
        "Linear algebra: vectors, dot product, matrix multiplication",
        "Calculus: derivatives, chain rule, gradient intuition",
        "Supervised learning: regression vs classification",
        "Train/test split, cross-validation, overfitting/underfitting",
        "scikit-learn: pipelines, fit/transform/predict pattern",
        "Loss functions: MSE and cross-entropy — derived from first principles",
    ],
    SkillLevel.INTERMEDIATE: [
        "Gradient descent: batch, SGD, mini-batch — full derivation",
        "Regularization: L1/L2 geometry in weight space",
        "Decision trees and random forests: information gain, Gini impurity",
        "SVMs: maximum margin, kernel trick",
        "PCA: derivation via SVD, variance explained",
        "Neural networks: forward pass + backpropagation in NumPy from scratch",
        "SQL + DuckDB for analytical queries on large data",
        "Experiment tracking: MLflow runs, metrics, artifact logging",
    ],
    SkillLevel.ADVANCED: [
        "CNNs, RNNs, attention mechanism — math to code",
        "Transformers: self-attention derivation, positional encoding",
        "Optimization: Adam, AdamW, cosine LR schedules",
        "MLOps: model serving, versioning, drift detection",
        "LLMs: fine-tuning, LoRA, RLHF fundamentals",
        "Bayesian methods: MCMC, variational inference",
        "Time series: ARIMA, Prophet, neural forecasting",
        "Feature stores and online/offline serving architecture",
    ],
    SkillLevel.EXPERT: [
        "Custom CUDA kernels with Triton",
        "Causal inference: do-calculus, instrumental variables",
        "Reinforcement learning: policy gradients, PPO derivation",
        "Research replication: reading and implementing NeurIPS/ICML papers",
        "Production ML systems: real-time features, shadow deployment, canary",
    ],
}

DS_AI_TOOLS: list[ToolRecommendation] = [
    _tool("uv", "Fast Python package manager",
          linux="curl -LsSf https://astral.sh/uv/install.sh | sh",
          win="powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"",
          url="https://docs.astral.sh/uv/",
          why="100x faster installs; lockfiles; replaces pip+venv+conda", category="core"),
    _tool("marimo", "Reactive notebook (git-friendly)",
          linux="uv add marimo", url="https://marimo.io/",
          why="Notebooks as pure Python; reactive; no hidden state", category="core"),
    _tool("polars", "Lightning-fast DataFrames",
          linux="uv add polars", url="https://docs.pola.rs/",
          why="10-50x faster than pandas; lazy evaluation; expressive API", category="speed"),
    _tool("duckdb", "In-process analytical SQL",
          linux="uv add duckdb", url="https://duckdb.org/",
          why="Query CSV/Parquet/Arrow in-place; no server; faster than pandas", category="speed"),
    _tool("ruff", "Linter + formatter (all-in-one)",
          linux="uv add --dev ruff",
          why="Replaces flake8+black+isort; 100x faster", category="core"),
    _tool("mlflow", "Experiment tracking + model registry",
          linux="uv add mlflow", url="https://mlflow.org/",
          why="Track every run; compare experiments; register + serve models", category="mlops"),
    _tool("scikit-learn", "Classical ML algorithms",
          linux="uv add scikit-learn",
          why="Production-ready pipelines; consistent API; battle-tested", category="core"),
    _tool("pytorch", "Deep learning framework",
          linux="uv add torch torchvision", url="https://pytorch.org/",
          why="Industry standard; dynamic graphs; massive ecosystem", category="core"),
    _tool("hypothesis", "Property-based testing",
          linux="uv add --dev hypothesis",
          why="Generates edge cases automatically; catches silent data bugs", category="testing"),
    _tool("rich", "Beautiful terminal output",
          linux="uv add rich", url="https://rich.readthedocs.io/",
          why="Expert DSs use rich for readable debugging + progress bars", category="core"),
    _tool("dvc", "Data + model version control",
          linux="uv add dvc", url="https://dvc.org/",
          why="Git for large files; reproducible pipelines; team collaboration", category="mlops"),
]

# Real-world projects — learner builds progressively
DS_AI_PROJECTS = [
    {
        "id": "titanic_survival",
        "title": "Titanic Survival Predictor",
        "level": SkillLevel.BEGINNER,
        "concepts": ["Pandas: DataFrames", "scikit-learn: pipelines"],
        "hook": "Your first end-to-end ML pipeline — the classic beginner project that every DS has done",
        "description": "Load, clean, engineer features, train and evaluate a classifier",
    },
    {
        "id": "house_price_regression",
        "title": "House Price Prediction Engine",
        "level": SkillLevel.INTERMEDIATE,
        "concepts": ["Gradient descent: batch, SGD", "Regularization: L1/L2"],
        "hook": "Build a model Zillow-like companies use in production",
        "description": "Feature engineering, cross-validation, stacking, SHAP explanations",
    },
    {
        "id": "image_classifier",
        "title": "Custom Image Classifier",
        "level": SkillLevel.ADVANCED,
        "concepts": ["CNNs", "Transformers: self-attention"],
        "hook": "Train a model that can identify anything — from your phone's camera feed",
        "description": "Data augmentation, transfer learning, fine-tuning, deployment",
    },
    {
        "id": "mini_llm",
        "title": "Build a Mini-LLM from Scratch",
        "level": SkillLevel.EXPERT,
        "concepts": ["Transformers: self-attention derivation", "Custom CUDA kernels with Triton"],
        "hook": "Implement every line of a GPT-style model — know exactly what's inside the black box",
        "description": "Tokenization, attention, positional encoding, training loop, sampling",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# MEDICINE
# ══════════════════════════════════════════════════════════════════════════════

MEDICINE_CONCEPT_TREE: dict[SkillLevel, list[str]] = {
    SkillLevel.NOVICE: [
        "Clinical data types: vitals, labs, imaging, free-text notes",
        "ICD-10 and SNOMED CT: coding systems for diagnoses",
        "EHR structure and common data quality issues",
        "Biostatistics: sensitivity, specificity, PPV, NPV, ROC curves",
        "Python for clinical data: pandas with MIMIC-III demo",
    ],
    SkillLevel.BEGINNER: [
        "Survival analysis: Kaplan-Meier curves, log-rank test",
        "Clinical trial design: RCTs, bias types, p-values, confidence intervals",
        "FHIR: HL7 standard, SMART on FHIR apps",
        "De-identification: HIPAA Safe Harbor vs Expert Determination",
        "NLP for clinical notes: named entity recognition with spaCy",
    ],
    SkillLevel.INTERMEDIATE: [
        "Medical imaging: DICOM format, windowing, preprocessing pipelines",
        "CNN architectures for X-ray classification (CheXNet replication)",
        "Reimplementing clinical scores: APACHE II, SOFA, NEWS2",
        "Federated learning: theory and simulation across hospital cohorts",
        "AI fairness: subgroup analysis, bias sources in clinical ML",
    ],
    SkillLevel.ADVANCED: [
        "Genomics pipelines: variant calling, GWAS, polygenic risk scores",
        "Multimodal EHR models: labs + notes + imaging fusion",
        "LLMs for clinical decision support: RAG over medical literature",
        "Causal inference for treatment effect estimation (propensity matching)",
        "FDA SaMD guidance: clinical validation, post-market surveillance",
    ],
    SkillLevel.EXPERT: [
        "Real-world evidence: propensity matching, instrumental variables",
        "Clinical NLP at scale: ICD auto-coding production system",
        "Reproducible clinical research: DVC + MLflow in regulated context",
    ],
}

MEDICINE_TOOLS = [
    _tool("lifelines", "Survival analysis", linux="uv add lifelines"),
    _tool("pydicom", "DICOM medical imaging", linux="uv add pydicom"),
    _tool("medspacy", "Clinical NLP", linux="uv add medspacy"),
    _tool("pandas", "Data manipulation", linux="uv add pandas"),
    _tool("matplotlib", "Visualization", linux="uv add matplotlib"),
    _tool("scikit-learn", "ML algorithms", linux="uv add scikit-learn"),
    _tool("jupyter", "Interactive computation", linux="uv add jupyter"),
]

MEDICINE_PROJECTS = [
    {
        "id": "readmission_predictor",
        "title": "30-Day Readmission Predictor",
        "level": SkillLevel.INTERMEDIATE,
        "concepts": ["Survival analysis", "AI fairness"],
        "hook": "A model that every hospital needs — and you'll know exactly how to validate it",
        "description": "Build, evaluate, and audit a readmission risk model on MIMIC demo data",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# EDUCATION
# ══════════════════════════════════════════════════════════════════════════════

EDUCATION_CONCEPT_TREE: dict[SkillLevel, list[str]] = {
    SkillLevel.NOVICE: [
        "Learning science: spaced repetition, active recall, interleaving",
        "Bloom's taxonomy: from remembering to creating",
        "Formative vs summative assessment design",
        "Python basics: building a simple quiz from scratch",
    ],
    SkillLevel.BEGINNER: [
        "Knowledge tracing basics: Bayesian Knowledge Tracing (BKT)",
        "Learning analytics: engagement, dropout, and time-on-task metrics",
        "Instructional design: objectives → activities → assessment alignment",
        "AI APIs for automated content and question generation",
    ],
    SkillLevel.INTERMEDIATE: [
        "Bayesian Knowledge Tracing: implement BKT with PyTorch",
        "Recommendation systems for personalized learning paths",
        "NLP for automated grading and diagnostic feedback",
        "A/B testing educational interventions: power analysis, effect size",
    ],
    SkillLevel.ADVANCED: [
        "Intelligent tutoring systems: architecture and evaluation",
        "LLM-powered Socratic tutoring agents",
        "Multimodal learning: video + text + quiz pipelines",
    ],
    SkillLevel.EXPERT: [
        "Production LMS architecture: scalability and data privacy",
        "Educational data mining: research methods and publication",
        "Measuring causal impact: regression discontinuity, difference-in-differences",
    ],
}

EDUCATION_TOOLS = [
    _tool("gradio", "Interactive AI demos for students", linux="uv add gradio"),
    _tool("streamlit", "Rapid web apps for education", linux="uv add streamlit"),
    _tool("pandas", "Data analysis", linux="uv add pandas"),
    _tool("matplotlib", "Visualization", linux="uv add matplotlib"),
    _tool("jupyter", "Interactive notebooks", linux="uv add jupyter"),
]


# ══════════════════════════════════════════════════════════════════════════════
# SOFTWARE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

SE_CONCEPT_TREE: dict[SkillLevel, list[str]] = {
    SkillLevel.NOVICE: [
        "Git fundamentals: commit, branch, merge, rebase",
        "Python: functions, modules, packages, virtual environments",
        "Testing basics: unit tests with pytest, assert patterns",
        "REST APIs: HTTP verbs, status codes, JSON",
    ],
    SkillLevel.BEGINNER: [
        "Design patterns: Factory, Observer, Strategy — when and why",
        "SQL: joins, indexes, EXPLAIN query optimization",
        "Docker: containers, images, Compose for dev environments",
        "CI/CD: GitHub Actions pipeline from push to deploy",
    ],
    SkillLevel.INTERMEDIATE: [
        "System design: load balancing, caching, message queues",
        "Async Python: asyncio, concurrency models, event loops",
        "Database internals: B-trees, WAL, MVCC, connection pooling",
        "Security: OWASP Top 10, JWT, OAuth2 patterns",
    ],
    SkillLevel.ADVANCED: [
        "Distributed systems: Raft consensus, CAP theorem, eventual consistency",
        "Observability: distributed tracing, structured logging, SLOs",
        "Performance engineering: profiling, memory, CPython GIL",
        "API design: REST vs GraphQL vs gRPC — trade-offs",
    ],
    SkillLevel.EXPERT: [
        "Platform engineering: Kubernetes, service mesh, GitOps",
        "Compiler/interpreter internals: parsing, IR, codegen",
        "Large-scale refactoring: reading and evolving 100k+ line codebases",
    ],
}

SE_TOOLS = [
    _tool("ruff", "Linter + formatter", linux="uv add --dev ruff"),
    _tool("pytest", "Testing framework", linux="uv add --dev pytest"),
    _tool("httpx", "Modern async HTTP client", linux="uv add httpx"),
    _tool("rich", "Beautiful terminal output", linux="uv add rich"),
    _tool("typer", "CLI framework", linux="uv add typer"),
]


# ══════════════════════════════════════════════════════════════════════════════
# EXAM PREP
# ══════════════════════════════════════════════════════════════════════════════

EXAM_CONCEPT_TREE: dict[SkillLevel, list[str]] = {
    SkillLevel.NOVICE: [
        "Exam pattern analysis: syllabus, question types, marking scheme",
        "Building a study schedule using spaced repetition",
        "Active recall techniques: the Feynman method, practice tests",
        "Note-taking systems: Cornell method, concept mapping",
    ],
    SkillLevel.BEGINNER: [
        "Core subject fundamentals (domain-specific — filled by AI)",
        "Previous year question pattern analysis",
        "Time management: timed practice with error logging",
        "Weak area identification and targeted drilling",
    ],
    SkillLevel.INTERMEDIATE: [
        "Full-length mock tests with deep post-analysis",
        "Error taxonomy: conceptual vs careless vs time-pressure mistakes",
        "Speed + accuracy balance: subject-specific pacing strategy",
        "Cross-topic integration problems",
    ],
    SkillLevel.ADVANCED: [
        "Advanced problem-solving patterns from high-difficulty questions",
        "Peak performance under pressure: cognitive load management",
    ],
    SkillLevel.EXPERT: [
        "Teaching concepts to cement understanding (Feynman final stage)",
        "Contributing high-quality solutions to study communities",
    ],
}

EXAM_TOOLS = [
    _tool("anki", "Spaced repetition flashcards",
          linux="sudo apt install anki", mac="brew install --cask anki",
          win="winget install Anki.Anki",
          url="https://apps.ankiweb.net/",
          why="Most evidence-backed memorization tool — SM-2 algorithm"),
    _tool("obsidian", "Connected knowledge base",
          linux="snap install obsidian --classic", mac="brew install --cask obsidian",
          win="winget install Obsidian.Obsidian",
          url="https://obsidian.md/",
          why="Build a knowledge graph; see relationships between concepts"),
]


# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# BUSINESS
# ══════════════════════════════════════════════════════════════════════════════

BUSINESS_CONCEPT_TREE: dict[SkillLevel, list[str]] = {
    SkillLevel.NOVICE: [
        "Business fundamentals: revenue, cost, profit, unit economics",
        "Spreadsheet analysis: Excel/Google Sheets for business data",
        "Basic statistics for business: averages, trends, forecasting",
    ],
    SkillLevel.BEGINNER: [
        "Financial statements: P&L, balance sheet, cash flow analysis",
        "Market sizing: TAM, SAM, SOM estimation",
        "SQL for business analytics: cohort analysis, funnel metrics",
    ],
    SkillLevel.INTERMEDIATE: [
        "Product analytics: DAU/MAU, retention curves, churn modelling",
        "A/B testing: statistical significance, effect size, power analysis",
        "Data-driven strategy: metrics trees, OKRs, experimentation culture",
    ],
    SkillLevel.ADVANCED: [
        "Causal inference for business decisions: DiD, regression discontinuity",
        "ML for business: customer LTV, demand forecasting, personalisation",
        "Building data products: internal dashboards to customer-facing features",
    ],
    SkillLevel.EXPERT: [
        "Executive communication: translating data to board-level decisions",
        "Scaling analytics teams: tooling, culture, and measurement systems",
    ],
}

BUSINESS_TOOLS = [
    _tool("duckdb", "In-process analytical SQL", linux="uv add duckdb"),
    _tool("pandas", "Data manipulation", linux="uv add pandas"),
    _tool("plotly", "Interactive charts", linux="uv add plotly"),
    _tool("streamlit", "Rapid internal dashboards", linux="uv add streamlit"),
]


# ══════════════════════════════════════════════════════════════════════════════
# RESEARCH
# ══════════════════════════════════════════════════════════════════════════════

RESEARCH_CONCEPT_TREE: dict[SkillLevel, list[str]] = {
    SkillLevel.NOVICE: [
        "Research methodology: hypothesis formation, study design",
        "Literature review: systematic search, citation management",
        "Python for research: data collection, cleaning, basic analysis",
    ],
    SkillLevel.BEGINNER: [
        "Statistical inference: hypothesis tests, confidence intervals, effect sizes",
        "Reproducible research: version control, environments, notebooks",
        "Data visualization for research: publication-quality figures",
    ],
    SkillLevel.INTERMEDIATE: [
        "Experiment design: power analysis, randomization, blinding",
        "Advanced statistics: mixed models, survival analysis, Bayesian methods",
        "Automated data pipelines: ingestion, validation, transformation",
    ],
    SkillLevel.ADVANCED: [
        "Meta-analysis: pooling studies, heterogeneity, publication bias",
        "ML for research acceleration: automated hypothesis testing, NLP for literature",
        "Open science: pre-registration, data sharing, reproducibility standards",
    ],
    SkillLevel.EXPERT: [
        "Research leadership: grant writing, lab infrastructure, mentoring",
        "Peer review and publishing: journal selection, response to reviewers",
    ],
}

RESEARCH_TOOLS = [
    _tool("pandas", "Data manipulation", linux="uv add pandas"),
    _tool("scipy", "Scientific computing", linux="uv add scipy"),
    _tool("matplotlib", "Visualization", linux="uv add matplotlib"),
    _tool("jupyter", "Interactive notebooks", linux="uv add jupyter"),
    _tool("dvc", "Data version control", linux="uv add dvc"),
]


# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

DOMAIN_REGISTRY: dict[SpaceType, dict] = {
    SpaceType.DATA_SCIENCE: {
        "concept_tree": DS_AI_CONCEPT_TREE,
        "tools": DS_AI_TOOLS,
        "projects": DS_AI_PROJECTS,
        "domain_name": "Data Science & AI Engineering",
        "expert_description": (
            "Expert data scientists understand the math behind every algorithm, "
            "use fast tooling (polars, duckdb, marimo), version experiments with MLflow, "
            "and write production-grade Python."
        ),
    },
    SpaceType.AI_ENGINEERING: {
        "concept_tree": DS_AI_CONCEPT_TREE,
        "tools": DS_AI_TOOLS,
        "projects": DS_AI_PROJECTS,
        "domain_name": "AI Engineering",
        "expert_description": (
            "AI engineers build, fine-tune, and serve LLMs and deep learning models. "
            "They understand transformers from first principles and deploy with observability."
        ),
    },
    SpaceType.MEDICINE: {
        "concept_tree": MEDICINE_CONCEPT_TREE,
        "tools": MEDICINE_TOOLS,
        "projects": MEDICINE_PROJECTS,
        "domain_name": "Medical AI & Clinical Data Science",
        "expert_description": "Clinician-data-scientists who build and validate AI for healthcare.",
    },
    SpaceType.EDUCATION: {
        "concept_tree": EDUCATION_CONCEPT_TREE,
        "tools": EDUCATION_TOOLS,
        "projects": [],
        "domain_name": "Educational Technology & Learning Science",
        "expert_description": "Educators who build intelligent, adaptive learning systems.",
    },
    SpaceType.SOFTWARE_ENG: {
        "concept_tree": SE_CONCEPT_TREE,
        "tools": SE_TOOLS,
        "projects": [],
        "domain_name": "Software Engineering",
        "expert_description": "Software engineers who build reliable, scalable, maintainable systems.",
    },
    SpaceType.EXAM_PREP: {
        "concept_tree": EXAM_CONCEPT_TREE,
        "tools": EXAM_TOOLS,
        "projects": [],
        "domain_name": "Exam Preparation",
        "expert_description": "Structured preparation for competitive exams using proven learning science.",
    },
    SpaceType.BUSINESS: {
        "concept_tree": BUSINESS_CONCEPT_TREE,
        "tools": BUSINESS_TOOLS,
        "projects": [],
        "domain_name": "Business & Data Analytics",
        "expert_description": "Analysts and PMs who turn business data into decisions and products.",
    },
    SpaceType.RESEARCH: {
        "concept_tree": RESEARCH_CONCEPT_TREE,
        "tools": RESEARCH_TOOLS,
        "projects": [],
        "domain_name": "Research & Academia",
        "expert_description": "Researchers who design rigorous experiments and publish reproducible findings.",
    },
}


# ── Public API ─────────────────────────────────────────────────────────────────

def get_domain(space_type: SpaceType) -> dict:
    return DOMAIN_REGISTRY.get(space_type, DOMAIN_REGISTRY[SpaceType.DATA_SCIENCE])


def get_next_concepts(
    space_type: SpaceType,
    mastered: list[str],
    level: SkillLevel,
    limit: int = 5,
) -> list[str]:
    """Return pending concepts for the learner's current level."""
    tree = get_domain(space_type)["concept_tree"]
    mastered_set = set(mastered)
    pending = [c for c in tree.get(level, []) if c not in mastered_set]
    return pending[:limit] or tree.get(SkillLevel.NOVICE, [])[:3]


def get_available_projects(
    space_type: SpaceType,
    level: SkillLevel,
    completed_project_ids: list[str],
) -> list[dict]:
    """Return projects appropriate for the learner's level, excluding completed ones."""
    projects = get_domain(space_type).get("projects", [])
    level_order = list(SkillLevel)  # canonical order from enum definition
    level_idx = level_order.index(level) if level in level_order else 0
    completed = set(completed_project_ids)
    suitable = [
        p for p in projects
        if p["id"] not in completed
        and p["level"] in level_order
        and level_order.index(p["level"]) <= level_idx + 1
    ]
    return suitable[:3]
