# risk_engine.py — DeployIQ
# Fix #8: weighted scoring, more checks, overfitting signals, accuracy-F1 gap

def assess_risk(metrics: dict) -> dict:
    risks       = []
    score       = 0.0          # now float for weighted scoring
    explanation = []

    task_type    = metrics.get("task_type", "classification")
    dataset_size = metrics.get("dataset_size", 0)
    num_classes  = metrics.get("num_classes")
    detect_method = metrics.get("column_detection_method", "")

    # Note if columns were auto-detected
    if detect_method and detect_method != "alias match":
        explanation.append(
            f"Columns were auto-detected using '{detect_method}'. "
            f"Label column: '{metrics.get('label_column')}', "
            f"Prediction column: '{metrics.get('prediction_column')}'."
        )

    # ── Regression ─────────────────────────────────────────────────────────────
    if task_type == "regression":
        r2   = metrics.get("r2")   or 0.0
        rmse = metrics.get("rmse") or 0.0
        mae  = metrics.get("mae")  or 0.0

        explanation.append(
            "This is a regression model. "
            "Performance is evaluated using R², RMSE, and MAE."
        )

        # R² scoring — weighted by severity
        if r2 < 0:
            risks.append("Negative R² — Model Worse Than Baseline")
            explanation.append(
                "R² is negative, meaning the model performs worse than simply predicting "
                "the mean. This model should not be deployed."
            )
            score += 4.0
        elif r2 < 0.5:
            risks.append("Low Explanatory Power (R² < 0.5)")
            explanation.append(
                "The model explains less than 50% of variance. "
                "Predictions will be unreliable in production."
            )
            score += 2.5
        elif r2 < 0.75:
            risks.append("Moderate Explanatory Power (R² 0.5–0.75)")
            explanation.append(
                "The model explains a moderate amount of variance. "
                "Consider further tuning before full deployment."
            )
            score += 1.0

        # Dataset size — weighted
        if dataset_size < 100:
            risks.append("Critically Small Dataset (< 100 samples)")
            explanation.append(
                "Fewer than 100 samples — results are statistically unreliable."
            )
            score += 2.0
        elif dataset_size < 500:
            risks.append("Very Small Dataset (< 500 samples)")
            explanation.append(
                "Under 500 samples. Regression models are prone to overfitting at this size."
            )
            score += 1.5
        elif dataset_size < 1000:
            risks.append("Small Dataset (< 1,000 samples)")
            explanation.append(
                "Dataset is relatively small. Model may not generalise well."
            )
            score += 0.5

        # RMSE relative to MAE — overfitting signal
        if mae > 0 and rmse / mae > 3.0:
            risks.append("High RMSE/MAE Ratio — Outlier Sensitivity")
            explanation.append(
                "RMSE is more than 3× MAE, indicating the model makes very large errors "
                "on some samples. This is a sign of poor generalisation."
            )
            score += 1.0

    # ── Classification ─────────────────────────────────────────────────────────
    else:
        accuracy   = metrics.get("accuracy")   or 0.0
        precision  = metrics.get("precision")  or 0.0
        recall     = metrics.get("recall")     or 0.0
        f1         = metrics.get("f1_score")   or 0.0
        roc_auc    = metrics.get("roc_auc")
        class_dist = metrics.get("class_distribution") or {}
        minority_ratio = min(class_dist.values()) if class_dist else 1.0

        if num_classes and num_classes > 2:
            explanation.append(
                f"This is a multi-class classification model with {num_classes} classes. "
                "Performance is evaluated with weighted averaging."
            )

        # ── Accuracy checks ──────────────────────────────────────────────────
        if accuracy < 0.5:
            risks.append("Accuracy Below Random Chance (< 50%)")
            explanation.append(
                "Model accuracy is below 50%, which is worse than random guessing "
                "for binary classification. Do not deploy."
            )
            score += 3.0
        elif accuracy < 0.65:
            risks.append("Low Accuracy (< 65%)")
            explanation.append(
                "Accuracy is low. Most production use cases require at least 70–80%."
            )
            score += 1.5
        elif accuracy < 0.75:
            risks.append("Below-Average Accuracy (< 75%)")
            explanation.append(
                "Accuracy is below average for most production AI systems."
            )
            score += 0.5

        # ── Recall checks (most critical for safety) ─────────────────────────
        if recall < 0.5:
            risks.append("Critical Low Recall (< 50%)")
            explanation.append(
                "The model misses more than half of actual positive cases. "
                "In any safety-critical application this is unacceptable."
            )
            score += 2.5
        elif recall < 0.65:
            risks.append("Low Recall (< 65%)")
            explanation.append(
                "The model misses a significant number of positive cases. "
                "This creates blind spots in production."
            )
            score += 1.0

        # ── Precision-Recall imbalance ────────────────────────────────────────
        if precision > 0 and recall > 0:
            pr_gap = abs(precision - recall)
            if pr_gap > 0.25:
                risks.append(f"Precision-Recall Gap ({pr_gap:.0%})")
                explanation.append(
                    f"There is a {pr_gap:.0%} gap between precision and recall. "
                    "This often means the model is biased toward one class. "
                    "Review the decision threshold."
                )
                score += 1.0

        # ── Accuracy vs F1 gap — class imbalance signal (fix #8) ─────────────
        if f1 > 0:
            acc_f1_gap = accuracy - f1
            if acc_f1_gap > 0.15:
                risks.append("Accuracy–F1 Divergence (Class Imbalance Signal)")
                explanation.append(
                    f"Accuracy ({accuracy:.0%}) is much higher than F1 ({f1:.0%}). "
                    "This strongly suggests class imbalance is inflating accuracy. "
                    "The model may be predicting the majority class almost always."
                )
                score += 1.5

        # ── ROC-AUC check ─────────────────────────────────────────────────────
        if roc_auc is not None:
            if roc_auc < 0.6:
                risks.append("Poor ROC-AUC (< 0.60)")
                explanation.append(
                    f"ROC-AUC of {roc_auc:.2f} is near random (0.5). "
                    "The model has poor discriminative ability."
                )
                score += 1.5
            elif roc_auc < 0.7:
                risks.append("Below-Average ROC-AUC (< 0.70)")
                explanation.append(
                    f"ROC-AUC of {roc_auc:.2f} indicates weak discrimination between classes."
                )
                score += 0.5

        # ── Class imbalance ───────────────────────────────────────────────────
        if minority_ratio < 0.1:
            risks.append("Severe Class Imbalance (minority < 10%)")
            explanation.append(
                f"The minority class makes up only {minority_ratio:.0%} of the data. "
                "The model is likely ignoring it entirely. Use oversampling or class weights."
            )
            score += 2.0
        elif minority_ratio < 0.2:
            risks.append("Significant Class Imbalance (minority < 20%)")
            explanation.append(
                f"The minority class is only {minority_ratio:.0%} of data. "
                "Model performance on minority class may be poor."
            )
            score += 1.0
        elif minority_ratio < 0.3:
            risks.append("Mild Class Imbalance")
            explanation.append(
                "Dataset shows mild imbalance. Monitor minority class performance closely."
            )
            score += 0.5

        # ── Dataset size ──────────────────────────────────────────────────────
        if dataset_size < 100:
            risks.append("Critically Small Dataset (< 100 samples)")
            explanation.append("Fewer than 100 samples — results are not statistically reliable.")
            score += 2.0
        elif dataset_size < 500:
            risks.append("Very Small Dataset (< 500 samples)")
            explanation.append("Under 500 samples. Classification metrics may be unstable.")
            score += 1.0
        elif dataset_size < 1000:
            risks.append("Small Dataset (< 1,000 samples)")
            explanation.append("Dataset size is relatively small for production deployment.")
            score += 0.5

        # ── Suspiciously perfect model — overfitting signal (fix #8) ─────────
        if accuracy >= 0.99 and f1 >= 0.99:
            risks.append("Suspiciously Perfect Metrics — Possible Data Leakage")
            explanation.append(
                "Accuracy and F1 are both ≥ 99%. This is rare in real-world data and often "
                "indicates data leakage (train/test contamination) or label overlap. "
                "Verify your evaluation split before deploying."
            )
            score += 2.0

        # ── Positive summary if genuinely strong ─────────────────────────────
        if accuracy >= 0.85 and f1 >= 0.80 and score < 1.0:
            explanation.insert(
                0,
                "Overall, the model demonstrates strong predictive performance "
                "across accuracy, precision, recall, and F1 metrics."
            )

    # ── Risk level from weighted score ────────────────────────────────────────
    if score < 1.0:
        level = "LOW"
        recommendation = (
            "The model shows acceptable performance and may proceed to controlled "
            "deployment or pilot testing. Continue monitoring in production."
        )
    elif score < 3.0:
        level = "MEDIUM"
        recommendation = (
            "The model requires additional validation and improvement before "
            "full-scale deployment. Address the risk flags above."
        )
    else:
        level = "HIGH"
        recommendation = (
            "High deployment risk detected. Do not deploy to production until "
            "the critical risk flags above are resolved."
        )

    return {
        "risks":          risks,
        "risk_score":     round(score, 2),
        "risk_level":     level,
        "recommendation": recommendation,
        "explanation":    explanation,
    }
