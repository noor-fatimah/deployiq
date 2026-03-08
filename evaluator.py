# evaluator.py — DeployIQ
# Handles any CSV format: string labels, int labels, float labels, multi-class, regression

import pandas as pd
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    classification_report,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

# ── Column name aliases ────────────────────────────────────────────────────────
LABEL_ALIASES = [
    "y_true", "actual", "label", "labels", "target", "targets",
    "true", "ground_truth", "groundtruth", "expected", "observed",
    "actuals", "true_label", "true_labels", "class", "classes",
    "outcome", "response", "gold", "annotation", "correct", "real",
]

PRED_ALIASES = [
    "y_pred", "predicted", "prediction", "predictions", "pred", "output",
    "outputs", "forecast", "forecasted", "estimate", "estimated",
    "pred_label", "pred_labels", "predicted_label", "predicted_labels",
    "score", "result", "inferred", "model_output", "classified", "classified_as",
]


def _find_column(columns, aliases):
    col_lower = {c.lower().strip(): c for c in columns}
    for alias in aliases:
        if alias.lower() in col_lower:
            return col_lower[alias.lower()]
    return None


def _infer_columns(df):
    columns = df.columns.tolist()

    label_col = _find_column(columns, LABEL_ALIASES)
    pred_col  = _find_column(columns, PRED_ALIASES)
    if label_col and pred_col and label_col != pred_col:
        return label_col, pred_col, "alias match"

    col_lower_map = {c.lower().strip(): c for c in columns}
    if not label_col:
        for alias in LABEL_ALIASES:
            for col_low, col_orig in col_lower_map.items():
                if alias in col_low:
                    label_col = col_orig
                    break
            if label_col:
                break
    if not pred_col:
        for alias in PRED_ALIASES:
            for col_low, col_orig in col_lower_map.items():
                if alias in col_low:
                    pred_col = col_orig
                    break
            if pred_col:
                break
    if label_col and pred_col and label_col != pred_col:
        return label_col, pred_col, "partial alias match"

    numeric_cols = df.select_dtypes(include=["number", "object", "category"]).columns.tolist()
    if len(numeric_cols) >= 2:
        cardinality = {c: df[c].nunique() for c in numeric_cols}
        sorted_cols = sorted(cardinality, key=lambda c: cardinality[c])
        c1, c2 = sorted_cols[0], sorted_cols[1]
        if c1 != c2:
            return c1, c2, "heuristic (low-cardinality columns)"

    if len(columns) >= 2:
        return columns[0], columns[1], "first two columns"

    return None, None, "none"


def _is_regression(series):
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().sum() > len(series) * 0.5:
        return False
    unique_count = numeric.nunique()
    unique_ratio = unique_count / max(len(numeric), 1)
    return unique_ratio > 0.05 and unique_count > 20


def _safe_roc_auc(y_true, y_pred):
    """Compute ROC-AUC safely for any binary setup. Never raises."""
    try:
        classes = sorted(y_true.unique())
        if len(classes) != 2:
            return None
        label_to_int = {classes[0]: 0, classes[1]: 1}
        y_true_int = y_true.map(label_to_int)
        y_pred_int = y_pred.map(label_to_int)
        mask = y_true_int.notna() & y_pred_int.notna()
        y_true_int = y_true_int[mask].astype(int)
        y_pred_int = y_pred_int[mask].astype(int)
        if len(y_true_int) == 0:
            return None
        return float(roc_auc_score(y_true_int, y_pred_int))
    except Exception:
        return None


def evaluate_model(df: pd.DataFrame):
    """
    Evaluate model performance from a pre-parsed DataFrame.
    The DataFrame is produced by file_parser.parse_file() and may originate
    from CSV, Excel, PDF, Word, JSON, or TXT files.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        raise ValueError("Invalid data: expected a DataFrame.")

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")

    if len(df) == 0:
        raise ValueError("The file contains no data rows.")

    if len(df.columns) < 2:
        raise ValueError(
            f"File must have at least 2 columns (found {len(df.columns)}). "
            "One for actual labels, one for predictions."
        )

    label_col, pred_col, method = _infer_columns(df)

    if not label_col or not pred_col:
        available = ", ".join(df.columns.tolist())
        raise ValueError(
            f"Could not find label and prediction columns.\n"
            f"Available columns: [{available}]\n"
            f"Rename your actual labels column to: y_true, actual, label, or target\n"
            f"Rename your predictions column to: y_pred, predicted, prediction, or pred"
        )

    y_true = df[label_col].copy()
    y_pred = df[pred_col].copy()

    if y_true.dtype == object:
        y_true = y_true.str.strip()
    if y_pred.dtype == object:
        y_pred = y_pred.str.strip()

    valid_mask = y_true.notna() & y_pred.notna()
    y_true = y_true[valid_mask].reset_index(drop=True)
    y_pred = y_pred[valid_mask].reset_index(drop=True)

    if len(y_true) == 0:
        raise ValueError("No valid rows found after removing missing values.")

    metrics = {
        "column_detection_method": method,
        "label_column":            label_col,
        "prediction_column":       pred_col,
        "dataset_size":            len(y_true),
        "total_rows":              len(df),
        "columns_available":       df.columns.tolist(),
    }

    # ── Regression ─────────────────────────────────────────────────────────────
    if _is_regression(y_true):
        metrics["task_type"]   = "regression"
        metrics["num_classes"] = None

        y_true_num = pd.to_numeric(y_true, errors="coerce")
        y_pred_num = pd.to_numeric(y_pred, errors="coerce")
        reg_mask   = y_true_num.notna() & y_pred_num.notna()
        y_true_num = y_true_num[reg_mask]
        y_pred_num = y_pred_num[reg_mask]

        metrics["mae"]  = float(mean_absolute_error(y_true_num, y_pred_num))
        metrics["mse"]  = float(mean_squared_error(y_true_num, y_pred_num))
        metrics["rmse"] = float(np.sqrt(metrics["mse"]))
        metrics["r2"]   = float(r2_score(y_true_num, y_pred_num))

        metrics["accuracy"]              = max(0.0, metrics["r2"])
        metrics["precision"]             = None
        metrics["recall"]                = None
        metrics["f1_score"]              = None
        metrics["roc_auc"]               = None
        metrics["confusion_matrix"]      = None
        metrics["classification_report"] = None
        metrics["class_distribution"]    = {}

    # ── Classification ─────────────────────────────────────────────────────────
    else:
        metrics["task_type"] = "classification"

        # Normalise everything to clean lowercase strings
        y_true = y_true.astype(str).str.strip().str.lower()
        y_pred = y_pred.astype(str).str.strip().str.lower()

        # Normalise common label variants to 0/1
        norm_map = {
            "true": "1",  "false": "0",
            "yes":  "1",  "no":    "0",
            "1.0":  "1",  "0.0":   "0",
            "positive": "1", "negative": "0",
            "pos": "1",   "neg": "0",
        }
        y_true = y_true.map(lambda x: norm_map.get(x, x))
        y_pred = y_pred.map(lambda x: norm_map.get(x, x))

        num_classes = len(y_true.unique())
        metrics["num_classes"] = num_classes

        metrics["accuracy"] = float(accuracy_score(y_true, y_pred))

        avg = "binary" if num_classes == 2 else "weighted"

        if num_classes == 2:
            classes   = sorted(y_true.unique())
            pos_label = classes[1]   # second in sorted order = positive class
            metrics["precision"] = float(precision_score(
                y_true, y_pred, average=avg, zero_division=0, pos_label=pos_label))
            metrics["recall"] = float(recall_score(
                y_true, y_pred, average=avg, zero_division=0, pos_label=pos_label))
            metrics["f1_score"] = float(f1_score(
                y_true, y_pred, average=avg, zero_division=0, pos_label=pos_label))
        else:
            metrics["precision"] = float(precision_score(
                y_true, y_pred, average=avg, zero_division=0))
            metrics["recall"] = float(recall_score(
                y_true, y_pred, average=avg, zero_division=0))
            metrics["f1_score"] = float(f1_score(
                y_true, y_pred, average=avg, zero_division=0))

        metrics["roc_auc"]               = _safe_roc_auc(y_true, y_pred)
        metrics["confusion_matrix"]      = confusion_matrix(y_true, y_pred).tolist()
        metrics["classification_report"] = classification_report(
            y_true, y_pred, output_dict=True)
        metrics["class_distribution"]    = y_true.value_counts(normalize=True).to_dict()

        metrics["mae"]  = None
        metrics["mse"]  = None
        metrics["rmse"] = None
        metrics["r2"]   = None

    return metrics
