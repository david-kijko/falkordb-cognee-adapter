from cognee.infrastructure.databases.dataset_database_handler import use_dataset_database_handler
from cognee.infrastructure.databases.graph import use_graph_adapter
from cognee.infrastructure.databases.vector import use_vector_adapter

from .falkor_adapter import FalkorDBAdapter
from .FalkorDatasetDatabaseHandlerGraphLocal import FalkorDatasetDatabaseHandlerGraphLocal
from .FalkorDatasetDatabaseHandlerVectorLocal import FalkorDatasetDatabaseHandlerVectorLocal

use_vector_adapter("falkor", FalkorDBAdapter)
use_graph_adapter("falkor", FalkorDBAdapter)
use_dataset_database_handler("falkor_graph_local", FalkorDatasetDatabaseHandlerGraphLocal, "falkor")
use_dataset_database_handler(
    "falkor_vector_local", FalkorDatasetDatabaseHandlerVectorLocal, "falkor"
)
