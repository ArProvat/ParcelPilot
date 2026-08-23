"""Authority-aware document ingestion and retrieval."""
from app.retrieval.ingest import import_document_corpus
from app.retrieval.retriever import DocumentRetriever
from app.retrieval.source_registry import DOCUMENT_SOURCES, SourceDefinition

__all__ = ["DOCUMENT_SOURCES", "DocumentRetriever", "SourceDefinition", "import_document_corpus"]
