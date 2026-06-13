import numpy as np

from configs.constants import UNKNOWN, DELIMITER
from common.util import map_status_group

def preprocess_test_df(test_df, encoders, scalers):
    test_df = test_df.sort_values(by="startTime")
    test_df["raw_service"] = test_df["service"]
    test_df["raw_operation"] = test_df["operation"]
    test_df["http_status"] = test_df["http_status"].astype(int).apply(map_status_group)
    test_df['service'] = test_df['app_id'] + DELIMITER + test_df['service']
    test_df['operation'] = test_df['app_id'] + DELIMITER + test_df['operation']
    
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