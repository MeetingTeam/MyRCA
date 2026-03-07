import os
import joblib
import torch
import numpy as np
import torch.nn as nn
import torch.optim as optim
import pandas as pd
from torch.utils.data import DataLoader, TensorDataset
from transformer_ae.model import TransformerAutoencoder
from common.safe_label_encoder import SafeLabelEncoder
from common.util import map_status_group
from configs.constants import UNKNOWN
from sklearn.preprocessing import StandardScaler

def preprocess_df(df):
    df["http_status"] = df["http_status"].astype(int).apply(map_status_group)

    # Encode numeric data
    encoders = {}
    for col in ["service", "operation"]:
        encoder = SafeLabelEncoder()
        df[col] = encoder.fit_transform(df[col].astype(str))
        encoders[col] = encoder

    # Scale numeric data
    scalers = {}
    for col in ["duration"]:
        scaler = StandardScaler()
        df[col] = scaler.fit_transform(df[[col]])
        scalers[col] = scaler

    # parent operation lookup
    span_to_op = dict(zip(df["spanId"], df["operation"]))
    op_unknown_index = encoders["operation"].get_unknown_index()
    df["parent_op"] = df["parentSpanId"].map(span_to_op).fillna(op_unknown_index).astype(int)

    span_to_service = dict(zip(df["spanId"], df["service"]))
    sc_unknown_index = encoders["service"].get_unknown_index()
    df["parent_service"] = df["parentSpanId"].map(span_to_service).fillna(sc_unknown_index).astype(int)

    return df[["service", "parent_service", "operation", "parent_op", "http_status", "duration"]], encoders, scalers

def build_sequences(df, seq_len, metric_cols, stride=1):
    grouped = df.groupby(["service", "parent_service", "operation", "parent_op", "http_status"], sort=False)

    services, parent_services, operations, parent_ops, statuses = [], [], [], [], []
    metrics_seq = []

    metric_cols = list(metric_cols)

    def append_context_features(s, ps, op, pop, h):
        services.append(s)
        parent_services.append(ps)
        operations.append(op)
        parent_ops.append(pop)
        statuses.append(h)    
    
    for (s, ps, op, pop, h), g in grouped:
        metrics = g[metric_cols].to_numpy(dtype=np.float32)
        n = metrics.shape[0]

        if n < seq_len:
            continue

        last_start = n - seq_len

        for i in range(0, last_start + 1, stride):
            append_context_features(s, ps, op, pop, h)
            metrics_seq.append(metrics[i:i + seq_len])

        if last_start % stride != 0:
            append_context_features(s, ps, op, pop, h)
            metrics_seq.append(metrics[last_start:last_start + seq_len])

    return (
        np.asarray(services),
        np.asarray(parent_services),
        np.asarray(operations),
        np.asarray(parent_ops),
        np.asarray(statuses),
        np.stack(metrics_seq),
    )

def train_model(data_set_path):
    df = pd.read_csv(data_set_path, keep_default_na=False, na_values=[])
    df, encoders, scalers = preprocess_df(df)

    seq_len = 20
    metric_cols = ["duration"]

    services, parent_services, operations, parent_ops, statuses, metrics_x = build_sequences(
        df, seq_len, metric_cols, 2
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    dataset = TensorDataset(
        torch.LongTensor(services),
        torch.LongTensor(parent_services),
        torch.LongTensor(operations),
        torch.LongTensor(parent_ops),
        torch.LongTensor(statuses),
        torch.FloatTensor(metrics_x),
    )

    loader = DataLoader(dataset, batch_size=64, shuffle=True)

    model = TransformerAutoencoder(
        service_vocab=encoders["service"].get_unknown_index() + 1,
        op_vocab=encoders["operation"].get_unknown_index() + 1,
        status_vocab=6,
        metrics_feature_num=len(metric_cols)
    ).to(device)

    # LOWER LEARNING RATE & WEIGHT DECAY
    optimizer = optim.Adam(model.parameters(), lr=5e-4, weight_decay=1e-5)
    
    # SCHEDULER
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='min', factor=0.5, patience=5
    )
    
    criterion = nn.MSELoss()

    epochs = 50  # INCREASE EPOCHS
    for epoch in range(epochs):
        model.train()
        total_loss = 0

        for s, ps, op, pop, h, x in loader:
            s, ps, op, pop, h, x = s.to(device), ps.to(device), op.to(device), pop.to(device), h.to(device), x.to(device)

            recon = model(s, ps, op, pop, h, x)
            loss = criterion(recon, x)

            optimizer.zero_grad()
            loss.backward()
            
            # GRADIENT CLIPPING
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            
            optimizer.step()

            total_loss += loss.item()

        avg_loss = total_loss / len(loader)
        scheduler.step(avg_loss)
        
        current_lr = optimizer.param_groups[0]['lr']
        print(f"Epoch [{epoch+1}/{epochs}] Loss: {avg_loss:.6f} | LR: {current_lr:.6f}")

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    torch.save(model.state_dict(), os.path.join(BASE_DIR, "transformer_ae_model.pth"))
    joblib.dump(encoders, os.path.join(BASE_DIR, "transformer_ae_encoders.pkl"))
    joblib.dump(scalers, os.path.join(BASE_DIR, "transformer_ae_scalers.pkl"))