# AI Governance Rules Reference

This workspace uses AI governance rules defined in the thesis document for the Kubernetes Observability & Streaming Platform project.

## Active AI Rules

When working on this project, I should follow the governance rules and workflow specifications defined in:

**Primary Governance Document:** [ai-governance-rules-thesis.md](file:///D:/MyRCA/.agent/ai-governance-rules-thesis.md)

## Rule Application

The `ai-governance-rules-thesis.md` file defines:

1. **System Architecture** - Component definitions for Redpanda, Grafana Tempo, and Grafana OSS
2. **Workflow Governance (WF-001 to WF-010)** - End-to-end data flow rules from trace ingestion to ML model training
3. **Deployment Constraints (DC-001 to DC-004)** - Kubernetes deployment standards
4. **Helm Configuration (HG-001 to HG-003)** - Helm values and configuration standards
5. **Security Rules (SC-001 to SC-003)** - Simplified security for thesis/development
6. **Observability Integration (OI-001 to OI-002)** - Tempo-Grafana integration requirements
7. **Storage Rules (SR-001 to SR-003)** - PVC and retention policies
8. **Deployment Process (DP-001 to DP-002)** - Installation and access patterns

## Key Principles

- **Single Consumer Pattern**: Redpanda has ONLY ONE consumer (Anomaly Detection AI Model)
- **AWS S3 as Central Storage**: Three bucket architecture (tempo-traces, anomaly-data, ml-models)
- **AI Model as Gateway**: All traces flow through AI model before storage
- **Parquet Storage**: Anomalous traces stored in Parquet format for efficient analysis

When making changes to configurations, deployments, or code related to this platform, I should validate against these governance rules.
