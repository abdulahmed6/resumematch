"""Skill taxonomy and extraction.

A curated taxonomy of technical skills with aliases. Extraction uses
word-boundary regex matching so that e.g. "go" doesn't match inside "google"
and "c++" / "node.js" are handled correctly.
"""
import re
from functools import lru_cache

# canonical skill -> aliases (all matched case-insensitively)
SKILL_TAXONOMY: dict[str, list[str]] = {
    "python": ["python", "python3"],
    "javascript": ["javascript", "js", "es6"],
    "typescript": ["typescript", "ts"],
    "java": ["java"],
    "go": ["golang", "go"],
    "rust": ["rust"],
    "c++": ["c++", "cpp"],
    "c#": ["c#", ".net", "dotnet"],
    "ruby": ["ruby", "rails", "ruby on rails"],
    "php": ["php", "laravel"],
    "sql": ["sql"],
    "react": ["react", "react.js", "reactjs"],
    "vue": ["vue", "vue.js", "vuejs"],
    "angular": ["angular"],
    "next.js": ["next.js", "nextjs"],
    "node.js": ["node.js", "nodejs", "node"],
    "django": ["django"],
    "flask": ["flask"],
    "fastapi": ["fastapi"],
    "spring": ["spring boot", "spring"],
    "graphql": ["graphql"],
    "rest apis": ["rest", "restful", "rest api", "rest apis"],
    "grpc": ["grpc"],
    "html/css": ["html", "css", "html/css", "sass", "tailwind"],
    "postgresql": ["postgresql", "postgres"],
    "mysql": ["mysql"],
    "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"],
    "elasticsearch": ["elasticsearch", "opensearch"],
    "kafka": ["kafka"],
    "rabbitmq": ["rabbitmq"],
    "celery": ["celery"],
    "spark": ["spark", "pyspark"],
    "airflow": ["airflow"],
    "dbt": ["dbt"],
    "snowflake": ["snowflake"],
    "docker": ["docker", "containers", "containerization"],
    "kubernetes": ["kubernetes", "k8s"],
    "terraform": ["terraform"],
    "ansible": ["ansible"],
    "aws": ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "gcp": ["gcp", "google cloud", "bigquery"],
    "azure": ["azure"],
    "ci/cd": ["ci/cd", "cicd", "jenkins", "github actions", "gitlab ci"],
    "linux": ["linux", "unix"],
    "git": ["git"],
    "monitoring": ["prometheus", "grafana", "datadog", "observability", "monitoring"],
    "machine learning": ["machine learning", "ml"],
    "deep learning": ["deep learning", "neural networks"],
    "pytorch": ["pytorch", "torch"],
    "tensorflow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "nlp": ["nlp", "natural language processing"],
    "llms": ["llm", "llms", "large language models", "gpt", "transformers"],
    "computer vision": ["computer vision", "opencv"],
    "mlops": ["mlops", "model deployment", "model serving"],
    "faiss": ["faiss", "vector search", "vector database", "pinecone", "weaviate"],
    "embeddings": ["embeddings", "sentence-transformers", "semantic search"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "data engineering": ["data engineering", "etl", "data pipelines", "data pipeline"],
    "data analysis": ["data analysis", "analytics", "a/b testing"],
    "tableau": ["tableau", "looker", "power bi"],
    "microservices": ["microservices", "microservice", "service-oriented"],
    "distributed systems": ["distributed systems", "distributed computing"],
    "system design": ["system design", "architecture design", "scalability"],
    "agile": ["agile", "scrum", "kanban"],
    "testing": ["unit testing", "pytest", "jest", "tdd", "integration testing"],
    "security": ["security", "oauth", "authentication", "encryption"],
    "websockets": ["websockets", "websocket"],
    "swift": ["swift", "ios development"],
    "kotlin": ["kotlin", "android development"],
    "react native": ["react native"],
    "flutter": ["flutter"],
}


@lru_cache(maxsize=1)
def _compiled_patterns() -> list[tuple[str, re.Pattern]]:
    patterns = []
    for canonical, aliases in SKILL_TAXONOMY.items():
        # longer aliases first so "react native" wins over "react"
        for alias in sorted(aliases, key=len, reverse=True):
            escaped = re.escape(alias)
            patterns.append((canonical, re.compile(rf"(?<![\w+#.]){escaped}(?![\w+#])", re.IGNORECASE)))
    return patterns


def extract_skills(text: str) -> list[str]:
    """Return sorted list of canonical skills mentioned in the text."""
    if not text:
        return []
    found: set[str] = set()
    for canonical, pattern in _compiled_patterns():
        if canonical in found:
            continue
        if pattern.search(text):
            found.add(canonical)
    return sorted(found)


def all_skills() -> list[str]:
    return sorted(SKILL_TAXONOMY.keys())
