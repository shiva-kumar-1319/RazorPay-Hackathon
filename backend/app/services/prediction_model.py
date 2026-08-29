"""Recovery Prediction Model — GradientBoosting classifier predicting P(recovery success) per action.

Day 8 deliverable: trains on synthetic domain-knowledge-derived data, produces calibrated
probabilities, and provides explainable feature importances.  Designed for zero-cold-start
operation — the model bootstraps itself from realistic synthetic data on first import and
can later be retrained from real recovery outcomes.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split

from backend.app.models.recovery import ActionType, CustomerIntelligence

logger = logging.getLogger("recoverx.prediction_model")

# ============================================================================
# 1. FEATURE SCHEMA — Fixed-width 26-dimensional vector
# ============================================================================

FEATURE_NAMES: list[str] = [
    # Transaction features (5)
    "amount",
    "log_amount",
    "is_high_value",
    "hour_of_day",
    "is_business_hours",
    # Customer intelligence features (6)
    "customer_success_rate",
    "customer_recovery_rate",
    "customer_risk_score",
    "customer_failure_streak",
    "customer_avg_txn_value",
    "customer_total_txns",
    # Failure category one-hot (4)
    "cat_temporary",
    "cat_payment_method",
    "cat_customer_action",
    "cat_hard_failure",
    # Action type one-hot (8)
    "act_retry_same",
    "act_switch_upi",
    "act_switch_card",
    "act_switch_netbanking",
    "act_delayed_retry",
    "act_customer_notification",
    "act_payment_link",
    "act_stop_recovery",
    # Behavioral segment one-hot (3 — collapsed into 3 discriminative flags)
    "seg_vip",
    "seg_high_risk",
    "seg_new_customer",
]

CATEGORY_INDEX = {
    "TEMPORARY": 0,
    "PAYMENT_METHOD": 1,
    "CUSTOMER_ACTION": 2,
    "HARD_FAILURE": 3,
}

ACTION_INDEX = {
    ActionType.RETRY_SAME_METHOD: 0,
    ActionType.SWITCH_TO_UPI: 1,
    ActionType.SWITCH_TO_CARD: 2,
    ActionType.SWITCH_TO_NETBANKING: 3,
    ActionType.DELAYED_RETRY: 4,
    ActionType.CUSTOMER_NOTIFICATION: 5,
    ActionType.PAYMENT_LINK: 6,
    ActionType.STOP_RECOVERY: 7,
}

SEGMENT_FLAGS = {
    "VIP_HIGH_VALUE": (1, 0, 0),
    "HIGH_FAILURE_RISK": (0, 1, 0),
    "FIRST_TIME_SHOPPER": (0, 0, 1),
    "NEW_CUSTOMER": (0, 0, 1),
    "UPI_MOBILE_PREFERRED": (0, 0, 0),
    "CARD_DECLINE_PRONE_RECOVERABLE": (0, 0, 0),
    "STANDARD": (0, 0, 0),
}


# ============================================================================
# 2. FEATURE EXTRACTOR
# ============================================================================


@dataclass
class RecoveryContext:
    """All contextual data needed for a single prediction."""

    amount: float
    failure_category: str  # TEMPORARY | PAYMENT_METHOD | CUSTOMER_ACTION | HARD_FAILURE
    action_type: ActionType
    hour_of_day: int = 12
    customer_success_rate: float = 0.5
    customer_recovery_rate: float = 0.3
    customer_risk_score: float = 0.1
    customer_failure_streak: int = 0
    customer_avg_txn_value: float = 1000.0
    customer_total_txns: int = 5
    behavioral_segment: str = "STANDARD"


class RecoveryFeatureExtractor:
    """Transforms a RecoveryContext into a fixed-width numeric feature vector."""

    def extract(self, ctx: RecoveryContext) -> list[float]:
        """Produce the 26-dimensional feature vector from context."""
        features: list[float] = []

        # --- Transaction features (5) ---
        features.append(float(ctx.amount))
        features.append(math.log1p(float(ctx.amount)))
        features.append(1.0 if float(ctx.amount) > 10_000 else 0.0)
        features.append(float(ctx.hour_of_day) / 23.0)  # normalized to [0, 1]
        features.append(1.0 if 9 <= ctx.hour_of_day <= 18 else 0.0)

        # --- Customer intelligence features (6) ---
        features.append(float(ctx.customer_success_rate))
        features.append(float(ctx.customer_recovery_rate))
        features.append(float(ctx.customer_risk_score))
        features.append(min(float(ctx.customer_failure_streak) / 10.0, 1.0))
        features.append(math.log1p(float(ctx.customer_avg_txn_value)))
        features.append(min(float(ctx.customer_total_txns) / 100.0, 1.0))

        # --- Failure category one-hot (4) ---
        cat_vec = [0.0] * 4
        cat_idx = CATEGORY_INDEX.get(ctx.failure_category.upper(), 3)
        cat_vec[cat_idx] = 1.0
        features.extend(cat_vec)

        # --- Action type one-hot (8) ---
        act_vec = [0.0] * 8
        act_idx = ACTION_INDEX.get(ctx.action_type, 7)
        act_vec[act_idx] = 1.0
        features.extend(act_vec)

        # --- Behavioral segment flags (3) ---
        seg_flags = SEGMENT_FLAGS.get(ctx.behavioral_segment, (0, 0, 0))
        features.extend([float(f) for f in seg_flags])

        return features

    @staticmethod
    def from_recovery_data(
        amount: Decimal,
        failure_category: str,
        action_type: ActionType,
        customer_intel: CustomerIntelligence | None = None,
        hour_of_day: int = 12,
    ) -> RecoveryContext:
        """Build context from ORM models."""
        if customer_intel:
            return RecoveryContext(
                amount=float(amount),
                failure_category=failure_category,
                action_type=action_type,
                hour_of_day=hour_of_day,
                customer_success_rate=float(customer_intel.success_rate),
                customer_recovery_rate=float(customer_intel.recovery_rate),
                customer_risk_score=float(customer_intel.risk_score),
                customer_failure_streak=customer_intel.recent_failure_streak,
                customer_avg_txn_value=float(customer_intel.average_transaction_value),
                customer_total_txns=customer_intel.total_transactions,
                behavioral_segment=customer_intel.behavioral_segment,
            )
        return RecoveryContext(
            amount=float(amount),
            failure_category=failure_category,
            action_type=action_type,
            hour_of_day=hour_of_day,
        )


# ============================================================================
# 3. SYNTHETIC TRAINING DATA GENERATOR
# ============================================================================

# Base success probabilities encoding domain knowledge (category × action)
_BASE_PROBS: dict[str, dict[ActionType, float]] = {
    "TEMPORARY": {
        ActionType.DELAYED_RETRY: 0.78,
        ActionType.RETRY_SAME_METHOD: 0.55,
        ActionType.SWITCH_TO_UPI: 0.65,
        ActionType.CUSTOMER_NOTIFICATION: 0.40,
        ActionType.PAYMENT_LINK: 0.45,
        ActionType.SWITCH_TO_CARD: 0.35,
        ActionType.SWITCH_TO_NETBANKING: 0.40,
        ActionType.STOP_RECOVERY: 0.0,
    },
    "PAYMENT_METHOD": {
        ActionType.SWITCH_TO_UPI: 0.85,
        ActionType.PAYMENT_LINK: 0.65,
        ActionType.SWITCH_TO_NETBANKING: 0.58,
        ActionType.SWITCH_TO_CARD: 0.30,
        ActionType.CUSTOMER_NOTIFICATION: 0.50,
        ActionType.DELAYED_RETRY: 0.25,
        ActionType.RETRY_SAME_METHOD: 0.10,
        ActionType.STOP_RECOVERY: 0.0,
    },
    "CUSTOMER_ACTION": {
        ActionType.CUSTOMER_NOTIFICATION: 0.72,
        ActionType.PAYMENT_LINK: 0.60,
        ActionType.SWITCH_TO_UPI: 0.55,
        ActionType.DELAYED_RETRY: 0.40,
        ActionType.RETRY_SAME_METHOD: 0.20,
        ActionType.SWITCH_TO_CARD: 0.25,
        ActionType.SWITCH_TO_NETBANKING: 0.30,
        ActionType.STOP_RECOVERY: 0.0,
    },
    "HARD_FAILURE": {
        ActionType.STOP_RECOVERY: 0.0,
        ActionType.RETRY_SAME_METHOD: 0.01,
        ActionType.SWITCH_TO_UPI: 0.02,
        ActionType.SWITCH_TO_CARD: 0.01,
        ActionType.SWITCH_TO_NETBANKING: 0.01,
        ActionType.DELAYED_RETRY: 0.01,
        ActionType.CUSTOMER_NOTIFICATION: 0.02,
        ActionType.PAYMENT_LINK: 0.03,
    },
}

_SEGMENTS = list(SEGMENT_FLAGS.keys())


def generate_synthetic_training_data(
    n_samples: int = 5000,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate synthetic feature/label pairs grounded in domain knowledge.

    Returns (X, y) where X is (n_samples, 26) and y is (n_samples,) binary labels.
    """
    rng = random.Random(seed)
    np_rng = np.random.RandomState(seed)
    extractor = RecoveryFeatureExtractor()

    X_rows: list[list[float]] = []
    y_labels: list[int] = []

    categories = list(_BASE_PROBS.keys())
    actions = list(ActionType)

    for _ in range(n_samples):
        category = rng.choice(categories)
        action = rng.choice(actions)
        amount = round(rng.uniform(100, 50000), 2)
        hour = rng.randint(0, 23)
        segment = rng.choice(_SEGMENTS)

        success_rate = round(rng.uniform(0.2, 0.95), 4)
        recovery_rate = round(rng.uniform(0.0, 0.8), 4)
        risk_score = round(rng.uniform(0.01, 0.95), 4)
        failure_streak = rng.randint(0, 8)
        avg_txn = round(rng.uniform(200, 20000), 2)
        total_txns = rng.randint(1, 200)

        ctx = RecoveryContext(
            amount=amount,
            failure_category=category,
            action_type=action,
            hour_of_day=hour,
            customer_success_rate=success_rate,
            customer_recovery_rate=recovery_rate,
            customer_risk_score=risk_score,
            customer_failure_streak=failure_streak,
            customer_avg_txn_value=avg_txn,
            customer_total_txns=total_txns,
            behavioral_segment=segment,
        )

        features = extractor.extract(ctx)
        X_rows.append(features)

        # --- Label generation: base probability + adjustments + noise ---
        base_p = _BASE_PROBS[category].get(action, 0.1)

        # Customer-intelligence adjustments
        adjust = 0.0
        if segment == "VIP_HIGH_VALUE":
            adjust += 0.05
        elif segment == "HIGH_FAILURE_RISK":
            adjust -= 0.08
        elif segment in ("NEW_CUSTOMER", "FIRST_TIME_SHOPPER"):
            adjust -= 0.02

        if success_rate > 0.75:
            adjust += 0.04
        if failure_streak > 4:
            adjust -= 0.06
        if risk_score > 0.7:
            adjust -= 0.05

        # Business hours boost for notification/payment link
        if action in (ActionType.CUSTOMER_NOTIFICATION, ActionType.PAYMENT_LINK):
            if 9 <= hour <= 18:
                adjust += 0.03

        # High-value penalty for low-friction actions
        if amount > 10_000 and action == ActionType.RETRY_SAME_METHOD:
            adjust -= 0.03

        p = max(0.0, min(1.0, base_p + adjust + np_rng.normal(0, 0.08)))
        label = 1 if rng.random() < p else 0
        y_labels.append(label)

    return np.array(X_rows), np.array(y_labels)


# ============================================================================
# 4. PREDICTION MODEL
# ============================================================================


class RecoveryPredictionModel:
    """GradientBoosting classifier predicting P(successful recovery) per action.

    Bootstraps from synthetic data on initialization.  Thread-safe after training
    completes (the fitted estimator is read-only).
    """

    def __init__(self) -> None:
        self._model: CalibratedClassifierCV | None = None
        self._raw_model: GradientBoostingClassifier | None = None
        self._metrics: dict[str, float] = {}
        self._is_trained = False
        self._extractor = RecoveryFeatureExtractor()

    # --- Public API ---

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def train(self, n_samples: int = 5000, seed: int = 42) -> dict[str, float]:
        """Train the model from synthetic data.  Returns evaluation metrics."""
        logger.info("Training recovery prediction model with %d synthetic samples …", n_samples)
        X, y = generate_synthetic_training_data(n_samples=n_samples, seed=seed)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)

        base_clf = GradientBoostingClassifier(
            n_estimators=200,
            learning_rate=0.1,
            max_depth=4,
            min_samples_split=10,
            min_samples_leaf=5,
            subsample=0.8,
            random_state=seed,
        )
        base_clf.fit(X_train, y_train)
        self._raw_model = base_clf

        # Calibrate probabilities with isotonic regression
        cal_clf = CalibratedClassifierCV(base_clf, cv=3, method="isotonic")
        cal_clf.fit(X_train, y_train)
        self._model = cal_clf

        # Evaluate on held-out test set
        y_pred = cal_clf.predict(X_test)
        y_proba = cal_clf.predict_proba(X_test)[:, 1]

        self._metrics = {
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0.0)), 4),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0.0)), 4),
            "f1": round(float(f1_score(y_test, y_pred, zero_division=0.0)), 4),
            "auc": round(float(roc_auc_score(y_test, y_proba)), 4),
            "train_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
        }
        self._is_trained = True
        logger.info("Model trained — AUC=%.4f  Accuracy=%.4f  F1=%.4f", self._metrics["auc"], self._metrics["accuracy"], self._metrics["f1"])
        return self._metrics

    def predict_success_probability(self, features: list[float]) -> float:
        """Return calibrated P(success) ∈ [0, 1] for a single feature vector."""
        if not self._is_trained or self._model is None:
            raise RuntimeError("Model is not trained yet. Call train() first.")
        X = np.array(features).reshape(1, -1)
        proba = self._model.predict_proba(X)[0, 1]
        return round(float(proba), 4)

    def predict_from_context(self, ctx: RecoveryContext) -> float:
        """Convenience: extract features from context and predict."""
        # Hard failure with STOP_RECOVERY should have near-zero probability
        if ctx.failure_category.upper() == "HARD_FAILURE" and ctx.action_type == ActionType.STOP_RECOVERY:
            return 0.0
        features = self._extractor.extract(ctx)
        return self.predict_success_probability(features)

    def get_feature_importance(self) -> dict[str, float]:
        """Return feature name → importance mapping from the raw GBM."""
        if self._raw_model is None:
            return {}
        importances = self._raw_model.feature_importances_
        result = {}
        for i, name in enumerate(FEATURE_NAMES):
            result[name] = round(float(importances[i]), 6)
        return dict(sorted(result.items(), key=lambda kv: kv[1], reverse=True))

    def get_model_metrics(self) -> dict[str, Any]:
        """Return evaluation metrics from the last training run."""
        return {
            "is_trained": self._is_trained,
            **self._metrics,
            "feature_count": len(FEATURE_NAMES),
            "feature_names": FEATURE_NAMES,
        }

    @property
    def extractor(self) -> RecoveryFeatureExtractor:
        return self._extractor


# ============================================================================
# 5. SINGLETON — auto-trained on import
# ============================================================================

recovery_prediction_model = RecoveryPredictionModel()
recovery_prediction_model.train()
