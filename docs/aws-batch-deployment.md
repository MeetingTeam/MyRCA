# AWS Batch GPU Training Deployment Guide

Detailed walkthrough for deploying GPU-based training on AWS Batch Spot instances for 97% cost savings vs. Kubernetes 24/7 GPU nodes.

## Prerequisites

### AWS Permissions
Ensure you have admin access to:
- AWS IAM (create roles, policies)
- AWS Batch (compute environments, job queues, job definitions)
- Amazon EC2 (VPC, security groups)
- Amazon ECR (repositories)
- Amazon S3 (bucket access)

### Local Tools
```bash
# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install

# Install Docker
curl https://get.docker.com | bash

# Verify
aws --version  # AWS CLI 2.x
docker --version
```

### Environment Variables
```bash
export AWS_ACCOUNT_ID="123456789012"  # Your AWS account ID
export AWS_REGION="us-east-1"  # Batch region
export BATCH_SECURITY_GROUP="sg-xxxxxxxx"  # VPC security group
export MLFLOW_ELASTIC_IP="1.2.3.4"  # K8s cluster Elastic IP
export S3_BUCKET="kltn-anomaly-dateset-1"
export S3_REGION="ap-southeast-1"
```

## Phase 1: Set Up IAM Roles & Batch Infrastructure

**Script:** `infra/batch/setup-batch-infrastructure.sh`

This script creates:
- **BatchServiceRole:** Allows Batch service to manage EC2 instances
- **BatchJobRole:** Allows container jobs to access S3, ECR, K8s MLflow
- **Compute Environment:** Spot GPU instances with On-Demand fallback
- **Job Queue:** Routes jobs to compute environment with priority

### Step 1A: Create IAM Roles

```bash
# BatchServiceRole (Batch → EC2 management)
aws iam create-role --role-name BatchServiceRole \
  --assume-role-policy-document file://batch-trust-policy.json

aws iam attach-role-policy --role-name BatchServiceRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole

# BatchJobRole (Container → AWS service access)
aws iam create-role --role-name BatchJobRole \
  --assume-role-policy-document file://job-trust-policy.json

# Attach policies for S3, ECR
aws iam put-role-policy --role-name BatchJobRole --policy-name S3Access \
  --policy-document file://s3-policy.json

aws iam put-role-policy --role-name BatchJobRole --policy-name ECRAccess \
  --policy-document file://ecr-policy.json
```

**Trust Policy (job-trust-policy.json):**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": "ec2.amazonaws.com"
    },
    "Action": "sts:AssumeRole"
  }]
}
```

**S3 Policy (s3-policy.json):**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:GetObjectVersion"
    ],
    "Resource": [
      "arn:aws:s3:::kltn-anomaly-dateset-1/*",
      "arn:aws:s3:::kltn-anomaly-dateset-1"
    ]
  }]
}
```

### Step 1B: Create VPC & Security Group

```bash
# Use existing K8s VPC or create new
aws ec2 create-security-group \
  --group-name batch-gpu-sg \
  --description "Security group for Batch GPU instances" \
  --vpc-id vpc-xxxxxxxx

# Allow outbound HTTPS (for S3, ECR, MLflow)
aws ec2 authorize-security-group-egress \
  --group-id sg-xxxxxxxx \
  --protocol tcp --port 443 \
  --cidr 0.0.0.0/0
```

### Step 1C: Create Compute Environment

```bash
aws batch create-compute-environment \
  --compute-environment-name gpu-spot-ce \
  --type MANAGED \
  --state ENABLED \
  --compute-resources '{
    "type": "SPOT",
    "allocationStrategy": "SPOT_CAPACITY_OPTIMIZED",
    "minvCpus": 0,
    "maxvCpus": 8,
    "desiredvCpus": 0,
    "instanceTypes": ["g4dn.xlarge", "g4dn.2xlarge"],
    "subnets": ["subnet-xxxxxxxx"],
    "securityGroupIds": ["sg-xxxxxxxx"],
    "instanceRole": "arn:aws:iam::'$AWS_ACCOUNT_ID':instance-profile/BatchJobRole",
    "bidPercentage": 100,
    "spotIamFleetRole": "arn:aws:iam::aws:policy/service-role/AmazonEC2SpotFleetRole"
  }' \
  --service-role arn:aws:iam::$AWS_ACCOUNT_ID:role/BatchServiceRole \
  --region $AWS_REGION
```

### Step 1D: Create Job Queue

```bash
aws batch create-job-queue \
  --job-queue-name gpu-spot-queue \
  --state ENABLED \
  --priority 1 \
  --compute-environment-order '[
    {
      "order": 1,
      "computeEnvironment": "arn:aws:batch:'$AWS_REGION':'$AWS_ACCOUNT_ID':compute-environment/gpu-spot-ce"
    },
    {
      "order": 2,
      "computeEnvironment": "arn:aws:batch:'$AWS_REGION':'$AWS_ACCOUNT_ID':compute-environment/gpu-ondemand-ce"
    }
  ]' \
  --region $AWS_REGION
```

## Phase 2: Build & Push GPU Docker Image

**Script:** `infra/batch/push-ecr-image.sh`

### Step 2A: Create ECR Repository

```bash
aws ecr create-repository \
  --repository-name mlops-pipeline-gpu \
  --region $AWS_REGION
```

### Step 2B: Build GPU Docker Image

```bash
# From project root
docker build \
  --build-arg CUDA_VERSION=11.8.0 \
  -t mlops-pipeline-gpu:latest \
  -f Dockerfile.gpu .
```

**Dockerfile.gpu example:**
```dockerfile
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y \
    python3.10 python3-pip git libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
WORKDIR /app

RUN pip install --no-cache-dir -r requirements-gpu.txt

ENTRYPOINT ["python", "-m"]
```

### Step 2C: Push to ECR

```bash
# Authenticate
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Tag and push
docker tag mlops-pipeline-gpu:latest \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/mlops-pipeline-gpu:latest

docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/mlops-pipeline-gpu:latest
```

## Phase 3: Register Job Definitions

**Script:** `infra/batch/create-job-definitions.sh`

### Training Job Definition

```bash
aws batch register-job-definition \
  --job-definition-name mlops-train-job \
  --type container \
  --container-properties '{
    "image": "'$AWS_ACCOUNT_ID'.dkr.ecr.'$AWS_REGION'.amazonaws.com/mlops-pipeline-gpu:latest",
    "vcpus": 4,
    "memory": 15000,
    "jobRoleArn": "arn:aws:iam::'$AWS_ACCOUNT_ID':role/BatchJobRole",
    "environment": [
      {"name": "MLFLOW_TRACKING_URI", "value": "http://'$MLFLOW_ELASTIC_IP':30002"},
      {"name": "S3_BUCKET", "value": "'$S3_BUCKET'"},
      {"name": "S3_REGION", "value": "'$S3_REGION'"},
      {"name": "S3_ENDPOINT", "value": "s3.amazonaws.com"},
      {"name": "CUDA_VISIBLE_DEVICES", "value": "0"}
    ],
    "command": ["python", "-m", "tasks.training"]
  }' \
  --region $AWS_REGION
```

### Evaluation Job Definition

```bash
aws batch register-job-definition \
  --job-definition-name mlops-evaluate-job \
  --type container \
  --container-properties '{
    "image": "'$AWS_ACCOUNT_ID'.dkr.ecr.'$AWS_REGION'.amazonaws.com/mlops-pipeline-gpu:latest",
    "vcpus": 4,
    "memory": 15000,
    "jobRoleArn": "arn:aws:iam::'$AWS_ACCOUNT_ID':role/BatchJobRole",
    "environment": [
      {"name": "MLFLOW_TRACKING_URI", "value": "http://'$MLFLOW_ELASTIC_IP':30002"},
      {"name": "S3_BUCKET", "value": "'$S3_BUCKET'"},
      {"name": "S3_REGION", "value": "'$S3_REGION'"}
    ],
    "command": ["python", "-m", "tasks.evaluation"]
  }' \
  --region $AWS_REGION
```

## Phase 4: Configure Airflow

### Airflow AWS Connection

```bash
# Via Airflow CLI
airflow connections add aws_batch \
  --conn-type aws \
  --conn-extra '{"region_name": "us-east-1"}'

# Or if running on EC2/EKS with IAM role: no secrets needed
# The role automatically provides credentials
```

### K8s Secret for AWS Credentials (if needed)

```bash
# Optional: pre-stage credentials if not using IAM role
kubectl create secret generic airflow-aws-secret \
  --from-literal=AWS_ACCESS_KEY_ID="AKIA..." \
  --from-literal=AWS_SECRET_ACCESS_KEY="..." \
  -n airflow
```

## Phase 5: Validate Setup

**Script:** `infra/batch/validate-batch-setup.sh`

### Test Batch Job Submission

```bash
# Submit a test job to verify Batch setup
aws batch submit-job \
  --job-name test-gpu-job \
  --job-queue gpu-spot-queue \
  --job-definition mlops-train-job \
  --region $AWS_REGION
```

### Monitor Job Status

```bash
# List submitted jobs
aws batch list-jobs --job-queue gpu-spot-queue --region $AWS_REGION

# Describe specific job
aws batch describe-jobs \
  --jobs <job-id> \
  --region $AWS_REGION
```

### Verify GPU Access

Inside the running container, check GPU availability:

```bash
# This will be captured in CloudWatch Logs
docker run --gpus all nvidia/cuda:11.8.0-runtime ubuntu nvidia-smi

# In Batch logs (CloudWatch)
aws logs tail /aws/batch/job --follow --region $AWS_REGION
```

## Troubleshooting

### Spot Capacity Issues

If jobs stuck in RUNNABLE state:

```bash
# Check compute environment status
aws batch describe-compute-environments \
  --compute-environments gpu-spot-ce \
  --region $AWS_REGION

# Verify Spot quota
aws ec2 describe-spot-price-history \
  --instance-types g4dn.xlarge \
  --product-descriptions "Linux/UNIX" \
  --region $AWS_REGION
```

### Image Pull Failures

```bash
# Verify ECR image exists and is accessible
aws ecr describe-images \
  --repository-name mlops-pipeline-gpu \
  --region $AWS_REGION

# Check job role has ECR permissions
aws iam get-role-policy \
  --role-name BatchJobRole \
  --policy-name ECRAccess
```

### S3 Access Denied

```bash
# Verify bucket exists in correct region
aws s3api head-bucket \
  --bucket $S3_BUCKET \
  --region $S3_REGION

# Test S3 access from EC2 instance in Batch VPC
aws s3 ls s3://$S3_BUCKET/ --region $S3_REGION
```

### Cross-Region Access

Batch (us-east-1) accessing S3 (ap-southeast-1) requires:
1. **Network:** Security group allows outbound HTTPS
2. **IAM:** BatchJobRole has S3 permissions for the bucket
3. **DuckDB:** httpfs configured with S3 region + endpoint

```python
# mlops/tasks/s3_utils.py validates this:
con.execute(f"""
  SET s3_endpoint='s3.amazonaws.com';
  SET s3_region='ap-southeast-1';
""")
```

## Rollback

If migration fails, revert to K8s training:

```bash
# 1. Restore original DAG
git checkout HEAD~1 -- mlops/dags/training_pipeline_dag.py

# 2. Disable Batch resources (don't delete for recovery)
aws batch update-compute-environment \
  --compute-environment gpu-spot-ce \
  --state DISABLED \
  --region $AWS_REGION

aws batch update-job-queue \
  --job-queue gpu-spot-queue \
  --state DISABLED \
  --region $AWS_REGION

# 3. Restart Airflow DAG with original K8s tasks
airflow dags unpause training_pipeline
```

## Monitoring & Cost

### CloudWatch Metrics

```bash
# View Batch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Batch \
  --metric-name RunningCount \
  --dimensions Name=ComputeEnvironment,Value=gpu-spot-ce \
  --start-time 2026-05-01T00:00:00Z \
  --end-time 2026-05-08T00:00:00Z \
  --period 3600 \
  --statistics Average \
  --region $AWS_REGION
```

### Cost Monitoring

```bash
# Query Batch job run times
aws batch describe-jobs \
  --job-queue gpu-spot-queue \
  --region $AWS_REGION \
  | jq '.jobs[] | {jobId: .jobId, status: .status, runTime: (.stoppedAt - .startedAt)}'
```

### Estimated Monthly Cost

For a typical MLOps workload (4h training/week):
- **Spot GPU-hours:** ~16h/month × $0.35/h = **$5.60**
- **Data transfer:** S3 → Batch = **$1-2**
- **Total:** ~**$10/month** vs. $400 for always-on K8s GPU

## Next Steps

- [Pipeline Documentation](./pipeline.md) — MLOps training pipeline details
- [Infrastructure Guide](./infrastructure.md) — Full cluster setup
- [Setup Scripts](../infra/batch/) — Automated setup & validation

