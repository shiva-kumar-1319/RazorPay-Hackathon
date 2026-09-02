"""Application services for event-driven recovery workflows."""

from backend.app.services.customer_intelligence import (
    compute_customer_intelligence,
    create_customer,
    extract_customer_features,
    get_customer_detail,
    get_customer_payment_behavior,
    get_customer_recovery_history,
    list_customers,
    update_customer,
)
from backend.app.services.decision_engine import (
    ACTION_COST_MODEL,
    RecoveryDecisionEngine,
    ScoredAction,
    calculate_expected_value,
    recovery_decision_engine,
)
from backend.app.services.event_bus import EventBus, get_event_bus
from backend.app.services.event_ingestion import ingest_payment_failure
from backend.app.services.failure_intelligence import (
    CUSTOMER_ACTION_CODES,
    GATEWAY_CODE_MAPPINGS,
    HARD_STOP_CODES,
    PAYMENT_METHOD_CODES,
    TAXONOMY_CATALOG,
    TEMPORARY_CODES,
    FailureIntelligenceService,
    failure_intelligence_service,
)
from backend.app.services.outbox_publisher import OutboxPublisherService, outbox_publisher
from backend.app.services.prediction_model import (
    RecoveryFeatureExtractor,
    RecoveryPredictionModel,
    recovery_prediction_model,
)
from backend.app.services.recovery_policy import PolicyResult, evaluate_failure_policy
from backend.app.services.recovery_service import (
    RecoveryOrchestrator,
    get_pipeline_metrics,
    get_recovery_case_by_id,
    list_recovery_cases,
    recovery_orchestrator,
)

from backend.app.services.agent_tools import (
    AgentToolRegistry,
    agent_tool_registry,
    tool_create_recovery_plan,
    tool_get_failure_policy,
    tool_get_transaction_context,
    tool_request_execution,
    tool_score_candidates,
    tool_write_explanation,
)
from backend.app.services.recovery_agent import (
    PaymentRecoveryAgent,
    payment_recovery_agent,
)
from backend.app.services.recovery_execution import (
    RecoveryExecutionEngine,
    recovery_execution_engine,
)
from backend.app.services.evaluation_service import (
    EvaluationService,
    evaluation_service,
)

__all__ = [
    "ACTION_COST_MODEL",
    "AgentToolRegistry",
    "CUSTOMER_ACTION_CODES",
    "EvaluationService",
    "EventBus",
    "FailureIntelligenceService",
    "GATEWAY_CODE_MAPPINGS",
    "HARD_STOP_CODES",
    "OutboxPublisherService",
    "PAYMENT_METHOD_CODES",
    "PaymentRecoveryAgent",
    "PolicyResult",
    "RecoveryDecisionEngine",
    "RecoveryExecutionEngine",
    "RecoveryFeatureExtractor",
    "RecoveryOrchestrator",
    "RecoveryPredictionModel",
    "ScoredAction",
    "TAXONOMY_CATALOG",
    "TEMPORARY_CODES",
    "agent_tool_registry",
    "calculate_expected_value",
    "compute_customer_intelligence",
    "create_customer",
    "evaluate_failure_policy",
    "evaluation_service",
    "extract_customer_features",
    "failure_intelligence_service",
    "get_customer_detail",
    "get_customer_payment_behavior",
    "get_customer_recovery_history",
    "get_event_bus",
    "get_pipeline_metrics",
    "get_recovery_case_by_id",
    "ingest_payment_failure",
    "list_customers",
    "list_recovery_cases",
    "outbox_publisher",
    "payment_recovery_agent",
    "recovery_decision_engine",
    "recovery_execution_engine",
    "recovery_orchestrator",
    "recovery_prediction_model",
    "tool_create_recovery_plan",
    "tool_get_failure_policy",
    "tool_get_transaction_context",
    "tool_request_execution",
    "tool_score_candidates",
    "tool_write_explanation",
    "update_customer",
]
