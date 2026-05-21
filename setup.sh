#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Setting up FPA Scoping development environment...${NC}\n"

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Function to print section headers
section() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}\n"
}

# Function to print success
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print warning
warn() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Check Python version
section "Step 1: Checking Python version"
python_version=$(python3 --version | awk '{print $2}')
success "Python $python_version detected"

if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo -e "${YELLOW}Warning: Python 3.9+ is recommended, but older versions may work${NC}"
fi

# Create Python virtual environment
section "Step 2: Creating virtual environment"
if [ -d "venv" ]; then
    success "Virtual environment already exists"
else
    python3 -m venv venv
    success "Virtual environment created"
fi

# Activate virtual environment
source venv/bin/activate
success "Virtual environment activated"

# Upgrade pip, setuptools, wheel
section "Step 3: Upgrading pip and build tools"
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
success "pip, setuptools, and wheel upgraded"

# Install dependencies
section "Step 4: Installing Python dependencies"
if [ -f "fpa_web/requirements.txt" ]; then
    pip install -r fpa_web/requirements.txt
    success "Dependencies installed from fpa_web/requirements.txt"
else
    warn "fpa_web/requirements.txt not found"
    echo "Please install dependencies manually:"
    echo "  pip install -r fpa_web/requirements.txt"
    exit 1
fi

# Download checkpoint
section "Step 5: Downloading LingBot-Map checkpoint"
echo "This is a 4.6GB file. This step may take 10-30 minutes on first run."
echo ""
python fpa_web/scripts/download_checkpoint.py

# Setup database
section "Step 6: Setting up database"
cd fpa_web

# Run migrations
python manage.py migrate --settings=config.settings.local > /dev/null 2>&1
success "Database migrations applied"

# Create superuser (optional)
echo ""
echo "Creating admin user (optional - skip if already exists):"
echo "  Username: demo"
echo "  Password: demo"
echo ""

# Try to create superuser without prompting (will fail silently if user exists)
DJANGO_SUPERUSER_USERNAME=demo \
DJANGO_SUPERUSER_PASSWORD=demo \
DJANGO_SUPERUSER_EMAIL=demo@example.com \
python manage.py createsuperuser --noinput 2>/dev/null || true

success "Database setup complete"

# Summary
cd "$SCRIPT_DIR"
section "✅ Setup Complete!"

echo -e "${GREEN}FPA Scoping is ready to use!${NC}\n"
echo "To start the development server:"
echo -e "  ${YELLOW}cd $SCRIPT_DIR/fpa_web${NC}"
echo -e "  ${YELLOW}source ../venv/bin/activate${NC}"
echo -e "  ${YELLOW}python manage.py runserver${NC}"
echo ""
echo "Access the web app:"
echo -e "  ${YELLOW}http://localhost:8000${NC}"
echo ""
echo "Admin credentials:"
echo -e "  Username: ${YELLOW}demo${NC}"
echo -e "  Password: ${YELLOW}demo${NC}"
echo ""
echo "Documentation:"
echo -e "  ${YELLOW}- README.md${NC}           (Project overview)"
echo -e "  ${YELLOW}- GITHUB_PUSH_GUIDE.md${NC} (Large file handling)"
echo -e "  ${YELLOW}- GCP_DEPLOYMENT_GUIDE.md${NC} (Production deployment)"
echo ""
