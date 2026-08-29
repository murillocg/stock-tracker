"""Persistence: Protocols, the DynamoDB implementations, and in-memory fakes."""

from shared.repository.dynamodb import (
    LIST_TYPE_INDEX,
    DynamoDbSnapshotRepository,
    DynamoDbStockRepository,
    DynamoDbTransactionRepository,
)
from shared.repository.memory import (
    InMemorySnapshotRepository,
    InMemoryStockRepository,
    InMemoryTransactionRepository,
)
from shared.repository.protocol import (
    SnapshotRepository,
    StockRepository,
    TransactionRepository,
)

__all__ = [
    "LIST_TYPE_INDEX",
    "DynamoDbSnapshotRepository",
    "DynamoDbStockRepository",
    "DynamoDbTransactionRepository",
    "InMemorySnapshotRepository",
    "InMemoryStockRepository",
    "InMemoryTransactionRepository",
    "SnapshotRepository",
    "StockRepository",
    "TransactionRepository",
]
