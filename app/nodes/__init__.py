"""The eight pipeline steps. One file each, named after what it does."""

from app.nodes.deliver import deliver
from app.nodes.diff import diff
from app.nodes.extract import extract
from app.nodes.index import index
from app.nodes.ingest import ingest
from app.nodes.retrieve import retrieve
from app.nodes.score import score
from app.nodes.verify import needs_retry, verify, widen

__all__ = [
    "ingest", "index", "retrieve", "extract",
    "verify", "needs_retry", "widen",
    "score", "diff", "deliver",
]
