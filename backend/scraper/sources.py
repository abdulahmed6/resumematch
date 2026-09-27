"""Job posting sources.

`SyntheticSource` generates realistic, varied job postings deterministically
from a seed. It stands in for real job-board connectors: it exposes the same
`fetch(count)` interface a real scraper would, so a live source (RSS, API,
HTML scraping) can be dropped in without touching the pipeline.
"""
import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

ROLES: list[tuple[str, list[str]]] = [
    ("Backend Engineer", ["python", "fastapi", "postgresql", "redis", "docker", "rest apis", "microservices", "testing"]),
    ("Frontend Engineer", ["javascript", "typescript", "react", "html/css", "testing", "next.js", "git"]),
    ("Full Stack Engineer", ["python", "react", "typescript", "node.js", "postgresql", "docker", "rest apis"]),
    ("Data Engineer", ["python", "sql", "spark", "airflow", "kafka", "data engineering", "aws", "dbt"]),
    ("Data Scientist", ["python", "pandas", "numpy", "scikit-learn", "sql", "machine learning", "data analysis"]),
    ("ML Engineer", ["python", "pytorch", "machine learning", "mlops", "docker", "kubernetes", "aws", "llms"]),
    ("DevOps Engineer", ["docker", "kubernetes", "terraform", "aws", "ci/cd", "linux", "monitoring", "ansible"]),
    ("Site Reliability Engineer", ["kubernetes", "monitoring", "linux", "go", "terraform", "distributed systems", "ci/cd"]),
    ("Mobile Engineer", ["swift", "kotlin", "react native", "rest apis", "git", "testing"]),
    ("Platform Engineer", ["go", "kubernetes", "grpc", "distributed systems", "postgresql", "kafka", "system design"]),
    ("Search Engineer", ["python", "elasticsearch", "faiss", "embeddings", "nlp", "machine learning", "distributed systems"]),
    ("NLP Engineer", ["python", "nlp", "llms", "pytorch", "embeddings", "machine learning", "mlops"]),
    ("Security Engineer", ["security", "python", "linux", "aws", "monitoring", "ci/cd"]),
    ("Data Analyst", ["sql", "python", "tableau", "data analysis", "pandas"]),
    ("Engineering Manager", ["system design", "agile", "microservices", "ci/cd", "distributed systems"]),
]

COMPANIES = [
    "Nimbus Labs", "Vectorly", "Quantail", "Brightpath AI", "Cobalt Systems", "Driftwood Data",
    "Emberline", "Fluxon", "Graphene Works", "Helios Cloud", "Indigo Metrics", "Juniper Stack",
    "Kelvin Analytics", "Luminary Tech", "Meridian Soft", "NovaForge", "Orbital Insights",
    "Pinewheel", "Quarry Digital", "Riverbend AI", "Signalhub", "TerraByte Co", "Umbra Security",
    "Verdant Apps", "Westwind Robotics", "Xylem Data", "YellowBrick Cloud", "Zephyr Networks",
]

LOCATIONS = [
    ("Minneapolis, MN", False), ("San Francisco, CA", False), ("New York, NY", False),
    ("Austin, TX", False), ("Seattle, WA", False), ("Chicago, IL", False), ("Denver, CO", False),
    ("Boston, MA", False), ("Atlanta, GA", False), ("Remote (US)", True), ("Remote (Global)", True),
    ("Remote (US)", True), ("Remote (Global)", True),  # weight remote higher
]

SENIORITIES = [("junior", 0.2), ("mid", 0.45), ("senior", 0.28), ("staff", 0.07)]

SALARY_BANDS = {"junior": (70, 105), "mid": (100, 150), "senior": (140, 200), "staff": (180, 260)}

INTRO_TEMPLATES = [
    "{company} is looking for a {seniority} {role} to join our {team} team.",
    "Join {company} as a {seniority} {role} and help us scale our platform to millions of users.",
    "{company} is hiring a {seniority} {role} to build the next generation of our product.",
    "We're {company} — and we need a {seniority} {role} who loves shipping quality software.",
]

TEAMS = ["core platform", "growth", "data infrastructure", "product engineering", "applied ML",
         "developer experience", "search & discovery", "payments", "trust & safety"]

RESPONSIBILITY_TEMPLATES = [
    "You will design, build and operate services that power our {team} products.",
    "Own features end to end: from design docs through deployment and monitoring.",
    "Collaborate with product and design to ship customer-facing improvements weekly.",
    "Mentor teammates through code review and pairing, raising the engineering bar.",
    "Improve reliability, observability and performance of our production systems.",
]

REQUIREMENT_TEMPLATE = "Requirements: {years}+ years of professional experience; strong skills in {skills_head}; familiarity with {skills_tail} is a big plus."

BENEFITS = [
    "We offer competitive compensation, equity, and a flexible hybrid schedule.",
    "Benefits include full health coverage, a learning stipend, and generous PTO.",
    "You'll get a home-office budget, annual retreats, and real ownership of your work.",
]

YEARS_BY_SENIORITY = {"junior": 1, "mid": 3, "senior": 5, "staff": 8}


@dataclass
class Posting:
    external_id: str
    title: str
    company: str
    location: str
    remote: bool
    seniority: str
    salary_min: float
    salary_max: float
    description: str
    skills: list[str] = field(default_factory=list)
    posted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SyntheticSource:
    """Deterministic generator of realistic job postings."""

    name = "synthetic"

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def _pick_seniority(self) -> str:
        r = self._rng.random()
        acc = 0.0
        for name, weight in SENIORITIES:
            acc += weight
            if r <= acc:
                return name
        return "mid"

    def _make_posting(self) -> Posting:
        rng = self._rng
        role, base_skills = rng.choice(ROLES)
        company = rng.choice(COMPANIES)
        location, remote = rng.choice(LOCATIONS)
        seniority = self._pick_seniority()
        lo, hi = SALARY_BANDS[seniority]
        salary_min = float(rng.randrange(lo, hi - 15, 5) * 1000)
        salary_max = float(salary_min + rng.randrange(15, 45, 5) * 1000)

        skills = list(base_skills)
        rng.shuffle(skills)
        skills = skills[: rng.randint(4, min(7, len(skills)))]

        head = skills[: max(2, len(skills) // 2)]
        tail = skills[max(2, len(skills) // 2):] or ["related tooling"]
        team = rng.choice(TEAMS)
        title = f"{seniority.capitalize()} {role}" if seniority in ("senior", "staff") else role

        parts = [
            rng.choice(INTRO_TEMPLATES).format(company=company, seniority=seniority, role=role, team=team),
            " ".join(rng.sample(RESPONSIBILITY_TEMPLATES, k=3)).format(team=team),
            REQUIREMENT_TEMPLATE.format(
                years=YEARS_BY_SENIORITY[seniority],
                skills_head=", ".join(head),
                skills_tail=", ".join(tail),
            ),
            rng.choice(BENEFITS),
        ]
        description = "\n\n".join(parts)

        raw = f"{company}|{title}|{location}|{description[:80]}|{rng.random()}"
        external_id = hashlib.sha1(raw.encode()).hexdigest()[:16]
        posted_at = datetime.now(timezone.utc) - timedelta(days=rng.randint(0, 30), hours=rng.randint(0, 23))

        return Posting(
            external_id=external_id, title=title, company=company, location=location,
            remote=remote, seniority=seniority, salary_min=salary_min, salary_max=salary_max,
            description=description, skills=sorted(skills), posted_at=posted_at,
        )

    def fetch(self, count: int) -> list[Posting]:
        return [self._make_posting() for _ in range(count)]


SOURCES = {"synthetic": SyntheticSource}


def get_source(name: str, seed: int | None = None):
    cls = SOURCES.get(name)
    if cls is None:
        raise ValueError(f"unknown source: {name}")
    return cls(seed=seed)
