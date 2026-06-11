#!/bin/bash
# GPU Worker Setup Script for GCP Compute Engine
# 
# Usage:
#   1. Create a Compute Engine instance with GPU (see instructions below)
#   2. SSH into the instance
#   3. curl -O https://raw.githubusercontent.com/curtisleewaterboer-arch/ss-tool/main/setup_gpu_worker.sh
#   4. chmod +x setup_gpu_worker.sh
#   5. ./setup_gpu_worker.sh
#
# This script:
#   - Installs CUDA 12.4 and cuDNN
#   - Installs PyTorch with GPU support
#   - Installs Celery, Redis, and dependencies
#   - Sets up systemd service for Celery worker

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🚀 Setting up GPU Worker on Compute Engine...${NC}\n"

# =============================================================================
# System Updates and Prerequisites
# =============================================================================
echo -e "${BLUE}Step 1: System updates${NC}"
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  curl \
  wget \
  git \
  python3-dev \
  python3-pip \
  libopenblas-dev \
  liblapack-dev \
  gfortran \
  pkg-config \
  libhdf5-dev

echo -e "${GREEN}✓ System packages installed${NC}\n"

# =============================================================================
# NVIDIA CUDA and cuDNN Installation
# =============================================================================
echo -e "${BLUE}Step 2: Installing CUDA 12.4${NC}"

# Download CUDA installer
wget https://developer.download.nvidia.com/compute/cuda/12.4.1/local_installers/cuda_12.4.1_550.54.15_linux.run
sudo sh cuda_12.4.1_550.54.15_linux.run --silent --driver --toolkit --samples
rm cuda_12.4.1_550.54.15_linux.run

# Set CUDA paths
echo 'export PATH=/usr/local/cuda-12.4/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.4/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

echo -e "${GREEN}✓ CUDA 12.4 installed${NC}\n"

echo -e "${BLUE}Step 3: Installing cuDNN${NC}"
# Note: cuDNN requires manual download from NVIDIA
# Assuming it's pre-uploaded to GCS or provided as argument
CUDNN_VERSION=${1:-"9.1.0.70"}
mkdir -p ~/cudnn
cd ~/cudnn
# If using GCS:
# gsutil cp gs://ss-tool-checkpoints/cudnn-12.4-${CUDNN_VERSION}.tar.gz .
# Otherwise, manually place the file and extract:
tar -xzf cudnn-12.4-${CUDNN_VERSION}.tar.gz
sudo cp cudnn-linux-x86_64-9.1.0_cuda12-archive/include/cudnn*.h /usr/local/cuda-12.4/include/
sudo cp cudnn-linux-x86_64-9.1.0_cuda12-archive/lib/libcudnn* /usr/local/cuda-12.4/lib64/
cd ~

echo -e "${GREEN}✓ cuDNN installed${NC}\n"

# =============================================================================
# Python Virtual Environment and Dependencies
# =============================================================================
echo -e "${BLUE}Step 4: Setting up Python environment${NC}"
python3 -m venv ~/gpu_worker_env
source ~/gpu_worker_env/bin/activate
pip install --upgrade pip setuptools wheel

echo -e "${GREEN}✓ Virtual environment created${NC}\n"

# =============================================================================
# Install PyTorch with GPU Support
# =============================================================================
echo -e "${BLUE}Step 5: Installing PyTorch with CUDA 12.4${NC}"
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

echo -e "${GREEN}✓ PyTorch installed${NC}\n"

# =============================================================================
# Install FPA Scoping Dependencies
# =============================================================================
echo -e "${BLUE}Step 6: Installing FPA Scoping dependencies${NC}"
mkdir -p ~/ss-tool
cd ~/ss-tool

# Clone repo or copy dependencies
# git clone https://github.com/curtisleewaterboer-arch/ss-tool.git .

# For now, assume requirements.txt is available
pip install \
  celery[redis]==5.3.5 \
  django==6.0.5 \
  psycopg2-binary==2.9.10 \
  google-cloud-storage \
  ffmpeg-python \
  opencv-python \
  numpy \
  scipy \
  pillow \
  viser

echo -e "${GREEN}✓ Dependencies installed${NC}\n"

# =============================================================================
# Create Celery Worker Startup Script
# =============================================================================
echo -e "${BLUE}Step 7: Creating Celery worker startup script${NC}"

cat > ~/start_celery_worker.sh << 'EOF'
#!/bin/bash
set -e

# Configuration - set these before running
export REDIS_URL=${REDIS_URL:-"redis://localhost:6379/0"}
export DJANGO_SETTINGS_MODULE="config.settings.gcp"
export SECRET_KEY=${SECRET_KEY:-"change-me-in-production"}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-""}
export POSTGRES_HOST=${POSTGRES_HOST:-"localhost"}

source ~/gpu_worker_env/bin/activate
cd ~/ss-tool/fpa_web

# Run Celery worker with GPU acceleration
celery -A config.celery worker \
  --loglevel=info \
  --concurrency=1 \
  --prefetch-multiplier=1 \
  --pool=solo \
  --max-tasks-per-child=1 \
  --broker=$REDIS_URL \
  --hostname=gpu-worker@%h

EOF

chmod +x ~/start_celery_worker.sh

echo -e "${GREEN}✓ Startup script created at ~/start_celery_worker.sh${NC}\n"

# =============================================================================
# Create Systemd Service (Optional)
# =============================================================================
echo -e "${BLUE}Step 8: Creating systemd service${NC}"

sudo tee /etc/systemd/system/celery-gpu-worker.service > /dev/null << EOF
[Unit]
Description=FPA Scoping GPU Worker (Celery)
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=\$(whoami)
WorkingDirectory=/home/\$(whoami)/ss-tool/fpa_web
Environment="REDIS_URL=redis://localhost:6379/0"
Environment="DJANGO_SETTINGS_MODULE=config.settings.gcp"
Environment="PATH=/home/\$(whoami)/gpu_worker_env/bin:/usr/local/cuda-12.4/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
Environment="LD_LIBRARY_PATH=/usr/local/cuda-12.4/lib64"
ExecStart=/home/\$(whoami)/start_celery_worker.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✓ Systemd service created${NC}\n"

# =============================================================================
# Verify GPU Access
# =============================================================================
echo -e "${BLUE}Step 9: Verifying GPU access${NC}"
nvidia-smi
python3 -c "import torch; print(f'PyTorch GPU available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"}')"

echo -e "${GREEN}✓ GPU verification complete${NC}\n"

# =============================================================================
# Summary
# =============================================================================
echo -e "${GREEN}✅ GPU Worker Setup Complete!${NC}\n"
echo "Next steps:"
echo "1. Copy your Django project to ~/ss-tool/"
echo "2. Set environment variables (see config below)"
echo "3. Run migrations if needed: python manage.py migrate --settings=config.settings.gcp"
echo "4. Start worker: ~/start_celery_worker.sh"
echo "5. Or enable systemd service: sudo systemctl enable --now celery-gpu-worker.service"
echo ""
echo "For local testing with remote GPU worker:"
echo "  - Keep REDIS_URL=redis://localhost:6379/0 (your local Redis)"
echo "  - SSH tunnel to Compute Engine instance if Redis is there"
echo ""
echo "For production:"
echo "  - Use Cloud Memorystore Redis: REDIS_URL=redis://10.0.0.3:6379/0"
echo "  - Use Cloud SQL: POSTGRES_HOST=cloudsql-proxy, POSTGRES_PORT=5432"
echo ""
