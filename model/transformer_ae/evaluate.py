import os
import joblib
import torch
import numpy as np
import pandas as pd
import torch.nn as nn

from torch.utils.data import DataLoader, TensorDataset
from transformer_ae.model import TransformerAutoencoder
from configs.constants import UNKNOWN
from common.util import map_status_group

def preprocess_test_df(test_df, encoders, scalers):
    # test_df = test_df.sort_values(by="startTime")
    test_df["raw_service"] = test_df["service"]
    test_df["raw_operation"] = test_df["operation"]
    test_df["http_status"] = test_df["http_status"].astype(int).apply(map_status_group)
    
    # Encode categorical data (LabelEncoder)
    for col in ["service", "operation"]:
        encoder = encoders[col]
        test_df[col] = encoder.transform(test_df[col].astype(str))
    
    # Scale numeric data
    for col in ["duration"]:
        scaler = scalers[col]
        test_df[col] = scaler.transform(test_df[[col]])

    # parent operation lookup
    span_to_op = dict(zip(test_df["spanId"], test_df["operation"]))
    op_unknown_index = encoders["operation"].get_unknown_index()
    test_df["parent_op"] = test_df["parentSpanId"].map(span_to_op).fillna(op_unknown_index).astype(int)

    span_to_service = dict(zip(test_df["spanId"], test_df["service"]))
    sc_unknown_index = encoders["service"].get_unknown_index()
    test_df["parent_service"] = test_df["parentSpanId"].map(span_to_service).fillna(sc_unknown_index).astype(int)

    return test_df

def build_sequences(df, seq_len, metric_cols, stride=1):
    grouped = df.groupby(["service", "parent_service", "operation", "parent_op", "http_status"], sort=False)

    services, parent_services, operations, parent_ops, statuses = [], [], [], [], []
    metrics_seq = []
    row_indices = []

    metric_cols = list(metric_cols)

    def append_context_features(s, ps, op, pop, h):
        services.append(s)
        parent_services.append(ps)
        operations.append(op)
        parent_ops.append(pop)
        statuses.append(h)    

    for (s, ps, op, pop, h), g in grouped:
        metrics = g[metric_cols].to_numpy(dtype=np.float32)
        indices = g.index.to_numpy()
        n = len(g)

        if n < seq_len:
            padded_metrics = np.zeros((seq_len, metrics.shape[1]), dtype=np.float32)
            padded_metrics[:n] = metrics

            padded_indices = np.full(seq_len, -1, dtype=indices.dtype)
            padded_indices[:n] = indices

            append_context_features(s, ps, op, pop, h)
            metrics_seq.append(padded_metrics)
            row_indices.append(padded_indices)
            continue

        last_start = n - seq_len
        for i in range(0, last_start + 1, stride):
            append_context_features(s, ps, op, pop, h)
            metrics_seq.append(metrics[i:i + seq_len])
            row_indices.append(indices[i:i + seq_len])

        if (last_start % stride) != 0:
            append_context_features(s, ps, op, pop, h)
            metrics_seq.append(metrics[last_start:last_start + seq_len])
            row_indices.append(indices[last_start:last_start + seq_len])

    return (
        np.asarray(services),
        np.asarray(parent_services),
        np.asarray(operations),
        np.asarray(parent_ops),
        np.asarray(statuses),
        np.stack(metrics_seq),
        np.stack(row_indices),
    )

def evaluate_model(test_data_path, export_result=True):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    model_path = os.path.join(BASE_DIR, "transformer_ae_model.pth")
    encoders = joblib.load(os.path.join(BASE_DIR, "transformer_ae_encoders.pkl"))
    scalers = joblib.load(os.path.join(BASE_DIR, "transformer_ae_scalers.pkl"))

    df = pd.read_csv(test_data_path)
    df = preprocess_test_df(df, encoders, scalers)

    seq_len = 20
    metric_cols = ["duration"]

    services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(
        df, seq_len, metric_cols, stride=2
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    dataset = TensorDataset(
        torch.LongTensor(services),
        torch.LongTensor(parent_services),
        torch.LongTensor(operations),
        torch.LongTensor(parent_ops),
        torch.LongTensor(statuses),
        torch.FloatTensor(metrics_x),
        torch.LongTensor(row_idx),
    )

    loader = DataLoader(dataset, batch_size=64, shuffle=False)

    model = TransformerAutoencoder(
        service_vocab=encoders["service"].get_unknown_index() + 1,
        op_vocab=encoders["operation"].get_unknown_index() + 1,
        status_vocab=6,
        metrics_feature_num=len(metric_cols)
    ).to(device)

    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()

    criterion = nn.MSELoss(reduction="none")
    df["anomaly_score"] = np.nan
    span_scores = {}

    with torch.no_grad():
        for s, ps, op, pop, h, x, row_ids in loader:
            s, ps, op, pop, h, x = s.to(device), ps.to(device), op.to(device), pop.to(device), h.to(device), x.to(device)

            recon = model(s, ps, op, pop, h, x)

            # (B, T, F) → per-timestep score (B, T)
            timestep_loss = criterion(recon, x).sum(dim=2).cpu().numpy()
            row_ids = row_ids.numpy()

            for b in range(len(row_ids)):
                for t_idx in range(seq_len):
                    row = row_ids[b, t_idx]
                    metric = x[b, t_idx]
                    if row == -1 or metric == 0:
                        continue

                    score = timestep_loss[b, t_idx]

                    # Add more score for http status = 5
                    if df.at[row, "span_status"] == 2 or df.at[row, "http_status"] == 5:
                        score += 1000
                    
                    if np.isnan(df.at[row, "anomaly_score"]):
                        df.at[row, "anomaly_score"] = score
                    else:
                        df.at[row, "anomaly_score"] = max(
                            df.at[row, "anomaly_score"], score
                        )
                    
                    span_scores[df.at[row, "spanId"]] = score

    if export_result:
        df.to_csv(os.path.join(BASE_DIR, "transformer_ae_pred.csv"), index=False)

    return span_scores