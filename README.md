# Kubernetes Observability Stack - MyRCA

## Project Overview
Thesis project implementing AI-driven observability platform with Redpanda, Tempo, and Grafana on Kubernetes.

## Architecture Components
- **Redpanda**: Kafka-compatible streaming platform
- **Grafana Tempo**: Distributed tracing backend with S3 storage
- **Grafana**: Visualization and monitoring dashboard
- **AI Anomaly Detection**: ML-based trace analysis

## Directory Structure
```
MyRCA/
├── opensource/
│   ├── redpanda/          # Redpanda Helm values
│   ├── tempo/             # Tempo Helm values & configs
│   └── grafana/           # Grafana Helm values
├── storage/               # StorageClass configurations
├── task.plan              # Deployment plan and checklist
└── .agent/                # AI agent rules and workflows
```

## Prerequisites
- Kubernetes cluster (AWS EKS recommended)
- Helm 3.x
- AWS S3 bucket for Tempo traces
- kubectl configured

## Quick Start

### 1. Deploy EBS CSI Driver
```bash
helm repo add aws-ebs-csi-driver https://kubernetes-sigs.github.io/aws-ebs-csi-driver
helm install aws-ebs-csi-driver aws-ebs-csi-driver/aws-ebs-csi-driver -n kube-system
```

### 2. Create Namespaces
```bash
kubectl create namespace redpanda
kubectl create namespace tempo
kubectl create namespace grafana
```

### 3. Deploy Stack
```bash
# Deploy Redpanda
helm install redpanda redpanda/redpanda -n redpanda -f opensource/redpanda/values-dev.yaml

# Create Tempo S3 credentials
kubectl create secret generic tempo-s3-credentials \
  --from-literal=access-key=<YOUR_ACCESS_KEY> \
  --from-literal=secret-key=<YOUR_SECRET_KEY> \
  -n tempo

# Deploy Tempo
helm install tempo grafana/tempo -n tempo -f opensource/tempo/values-dev.yaml

# Deploy Grafana
helm install grafana grafana/grafana -n grafana -f opensource/grafana/values-dev.yaml
```

### 4. Access Grafana
```bash
kubectl port-forward -n grafana svc/grafana 3000:80
# Access: http://localhost:3000
# Default credentials: admin/admin
```

## Configuration

### S3 Storage for Tempo
Tempo uses AWS S3 for long-term trace storage. Configure your S3 bucket and credentials:

1. Create S3 bucket in AWS Console
2. Create Kubernetes secret with AWS credentials
3. Update `opensource/tempo/values-dev.yaml` with bucket details

See [task.plan](task.plan) for detailed setup instructions.

## Documentation
- **[task.plan](task.plan)**: Complete deployment guide with step-by-step instructions
- **[.agent/ai-governance-rules-thesis.md](.agent/ai-governance-rules-thesis.md)**: Architecture and data flow documentation

## Security Notes
- AWS credentials are stored in Kubernetes Secrets
- S3 buckets use encryption at rest
- All services use ClusterIP (internal access only)
- Rotate credentials regularly

## Architecture Diagram
```
OpenTelemetry → Redpanda → AI Model → Tempo (S3) → Grafana
                                    ↓
                                   RCA
```

## License
MIT License - Thesis Project

## Author
Phung Quang Hung - UIT Thesis 2026
