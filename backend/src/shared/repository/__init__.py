"""Persistence: Protocols, the DynamoDB implementations, and in-memory fakes."""

from shared.repository.dynamodb import (
    LIST_TYPE_INDEX,
    DynamoDbSnapshotRepository,
    DynamoDbStockRepository,
)
from shared.repository.memory import InMemorySnapshotRepository, InMemoryStockRepository
from shared.repository.protocol import SnapshotRepository, StockRepository

__all__ = [
    "LIST_TYPE_INDEX",
    "DynamoDbSnapshotRepository",
    "DynamoDbStockRepository",
    "InMemorySnapshotRepository",
    "InMemoryStockRepository",
    "SnapshotRepository",
    "StockRepository",
]
