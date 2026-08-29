"""Unit tests for Recovery Prediction Model — Day 8."""

from decimal import Decimal

import numpy as np

from backend.app.models.recovery import ActionType
from backend.app.services.prediction_model import (
    FEATURE_NAMES,
    RecoveryContext,
    RecoveryFeatureExtractor,
    RecoveryPredictionModel,
    generate_synthetic_training_data,
    recovery_prediction_model,
)


class TestFeatureExtractor:
    """Verify feature vector shape and content."""

    def test_feature_vector_has_correct_dimension(self):
        extractor = RecoveryFeatureExtractor()
        ctx = RecoveryContext(
            amount=5000.0,
            failure_category="PAYMENT_METHOD",
            action_type=ActionType.SWITCH_TO_UPI,
        )
        features = extractor.extract(ctx)
        assert len(features) == 26
        assert len(features) == len(FEATURE_NAMES)

    def test_all_features_are_numeric(self):
        extractor = RecoveryFeatureExtractor()
        ctx = RecoveryContext(
            amount=1234.56,
            failure_category="TEMPORARY",
            action_type=ActionType.DELAYED_RETRY,
            hour_of_day=14,
            customer_success_rate=0.8,
            customer_recovery_rate=0.6,
            customer_risk_score=0.15,
            customer_failure_streak=2,
            customer_avg_txn_value=3000.0,
            customer_total_txns=50,
            behavioral_segment="VIP_HIGH_VALUE",
        )
        features = extractor.extract(ctx)
        for i, f in enumerate(features):
            assert isinstance(f, float), f"Feature {FEATURE_NAMES[i]} is not float: {type(f)}"

    def test_category_onehot_is_exclusive(self):
        """Only one category flag should be 1.0."""
        extractor = RecoveryFeatureExtractor()
        for cat in ("TEMPORARY", "PAYMENT_METHOD", "CUSTOMER_ACTION", "HARD_FAILURE"):
            ctx = RecoveryContext(amount=1000, failure_category=cat, action_type=ActionType.PAYMENT_LINK)
            features = extractor.extract(ctx)
            cat_flags = features[11:15]  # indices 11-14 are category one-hot
            assert sum(cat_flags) == 1.0, f"Category {cat} produced non-exclusive one-hot: {cat_flags}"

    def test_action_onehot_is_exclusive(self):
        """Only one action flag should be 1.0."""
        extractor = RecoveryFeatureExtractor()
        for action in ActionType:
            ctx = RecoveryContext(amount=1000, failure_category="TEMPORARY", action_type=action)
            features = extractor.extract(ctx)
            act_flags = features[15:23]  # indices 15-22 are action one-hot
            assert sum(act_flags) == 1.0, f"Action {action} produced non-exclusive one-hot: {act_flags}"

    def test_from_recovery_data_with_no_customer_intel(self):
        ctx = RecoveryFeatureExtractor.from_recovery_data(
            amount=Decimal("2500.00"),
            failure_category="CUSTOMER_ACTION",
            action_type=ActionType.CUSTOMER_NOTIFICATION,
        )
        assert ctx.amount == 2500.0
        assert ctx.failure_category == "CUSTOMER_ACTION"
        assert ctx.behavioral_segment == "STANDARD"

    def test_high_value_flag_correct(self):
        extractor = RecoveryFeatureExtractor()
        low_ctx = RecoveryContext(amount=5000, failure_category="TEMPORARY", action_type=ActionType.DELAYED_RETRY)
        high_ctx = RecoveryContext(amount=15000, failure_category="TEMPORARY", action_type=ActionType.DELAYED_RETRY)
        assert extractor.extract(low_ctx)[2] == 0.0  # is_high_value
        assert extractor.extract(high_ctx)[2] == 1.0


class TestSyntheticDataGeneration:
    """Verify training data generator produces valid data."""

    def test_generates_correct_shape(self):
        X, y = generate_synthetic_training_data(n_samples=100, seed=123)
        assert X.shape == (100, 26)
        assert y.shape == (100,)

    def test_labels_are_binary(self):
        X, y = generate_synthetic_training_data(n_samples=200, seed=456)
        assert set(np.unique(y)).issubset({0, 1})

    def test_both_classes_present(self):
        X, y = generate_synthetic_training_data(n_samples=500, seed=789)
        assert 0 in y
        assert 1 in y


class TestRecoveryPredictionModel:
    """Test the trained model singleton."""

    def test_model_is_trained(self):
        assert recovery_prediction_model.is_trained is True

    def test_auc_above_threshold(self):
        metrics = recovery_prediction_model.get_model_metrics()
        assert metrics["auc"] >= 0.75, f"AUC too low: {metrics['auc']}"

    def test_predictions_in_valid_range(self):
        ctx = RecoveryContext(
            amount=5000,
            failure_category="PAYMENT_METHOD",
            action_type=ActionType.SWITCH_TO_UPI,
        )
        prob = recovery_prediction_model.predict_from_context(ctx)
        assert 0.0 <= prob <= 1.0

    def test_hard_failure_stop_recovery_near_zero(self):
        ctx = RecoveryContext(
            amount=10000,
            failure_category="HARD_FAILURE",
            action_type=ActionType.STOP_RECOVERY,
        )
        prob = recovery_prediction_model.predict_from_context(ctx)
        assert prob < 0.15, f"HARD_FAILURE + STOP_RECOVERY should be near zero, got {prob}"

    def test_payment_method_upi_higher_than_stop(self):
        upi_ctx = RecoveryContext(
            amount=5000,
            failure_category="PAYMENT_METHOD",
            action_type=ActionType.SWITCH_TO_UPI,
            customer_success_rate=0.8,
        )
        stop_ctx = RecoveryContext(
            amount=5000,
            failure_category="HARD_FAILURE",
            action_type=ActionType.STOP_RECOVERY,
        )
        upi_prob = recovery_prediction_model.predict_from_context(upi_ctx)
        stop_prob = recovery_prediction_model.predict_from_context(stop_ctx)
        assert upi_prob > stop_prob

    def test_feature_importance_non_empty(self):
        importances = recovery_prediction_model.get_feature_importance()
        assert len(importances) == 26
        assert all(v >= 0 for v in importances.values())

    def test_model_metrics_contains_required_fields(self):
        metrics = recovery_prediction_model.get_model_metrics()
        for key in ("is_trained", "accuracy", "precision", "recall", "f1", "auc"):
            assert key in metrics

    def test_retrain_produces_valid_model(self):
        fresh = RecoveryPredictionModel()
        assert fresh.is_trained is False
        metrics = fresh.train(n_samples=1000, seed=99)
        assert fresh.is_trained is True
        assert metrics["auc"] > 0.5
        # Can still predict after retraining
        ctx = RecoveryContext(amount=3000, failure_category="TEMPORARY", action_type=ActionType.DELAYED_RETRY)
        prob = fresh.predict_from_context(ctx)
        assert 0.0 <= prob <= 1.0
