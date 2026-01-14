#!/bin/bash
# =============================================================================
# DigitalOcean Droplet Setup Script
# =============================================================================
# Run this on a fresh Ubuntu 24.04 droplet to prepare for deployments.
#
# Usage:
#   1. SSH into your droplet: ssh root@YOUR_DROPLET_IP
#   2. Run: curl -sSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/droplet-setup.sh | bash
#   Or copy/paste the contents and run directly.
# =============================================================================

set -e  # Exit on any error

echo "============================================="
echo "Starting Droplet Setup"
echo "============================================="

# -----------------------------------------------------------------------------
# 1. System Updates
# -----------------------------------------------------------------------------
echo ""
echo "[1/6] Updating system packages..."
apt-get update
apt-get upgrade -y

# -----------------------------------------------------------------------------
# 2. Install Docker
# -----------------------------------------------------------------------------
echo ""
echo "[2/6] Installing Docker..."

# Remove old versions if any
apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Install dependencies
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker
systemctl start docker
systemctl enable docker

echo "Docker version: $(docker --version)"
echo "Docker Compose version: $(docker compose version)"

# -----------------------------------------------------------------------------
# 3. Create App Directory
# -----------------------------------------------------------------------------
echo ""
echo "[3/6] Creating app directory..."
mkdir -p ~/app
cd ~/app

# -----------------------------------------------------------------------------
# 4. Configure Firewall (UFW)
# -----------------------------------------------------------------------------
echo ""
echo "[4/6] Configuring firewall..."

# Install UFW if not present
apt-get install -y ufw

# Set default policies
ufw default deny incoming
ufw default allow outgoing

# Allow SSH (important - don't lock yourself out!)
ufw allow ssh

# Allow HTTP and HTTPS for Traefik
ufw allow 80/tcp
ufw allow 443/tcp

# Enable firewall
echo "y" | ufw enable

ufw status

# -----------------------------------------------------------------------------
# 5. Configure Swap (optional but recommended for 4GB RAM)
# -----------------------------------------------------------------------------
echo ""
echo "[5/6] Configuring swap space..."

# Check if swap already exists
if [ ! -f /swapfile ]; then
    # Create 2GB swap file
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile

    # Make swap permanent
    echo '/swapfile none swap sw 0 0' | tee -a /etc/fstab

    # Optimize swap settings
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' | tee -a /etc/sysctl.conf

    echo "Swap configured: $(swapon --show)"
else
    echo "Swap already exists"
fi

# -----------------------------------------------------------------------------
# 6. Create deploy user (optional but more secure than using root)
# -----------------------------------------------------------------------------
echo ""
echo "[6/6] Setup complete!"

echo ""
echo "============================================="
echo "DROPLET SETUP COMPLETE"
echo "============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Note your droplet IP address:"
echo "   curl -s ifconfig.me"
echo ""
echo "2. Update your DNS:"
echo "   Point jwhitezaps.atoaz.com -> $(curl -s ifconfig.me)"
echo ""
echo "3. Add GitHub Secrets (Settings > Secrets > Actions):"
echo "   DEPLOY_HOST = $(curl -s ifconfig.me)"
echo "   DEPLOY_USER = root"
echo "   SSH_PRIVATE_KEY = (your private key)"
echo ""
echo "4. Create production .env file:"
echo "   nano ~/app/.env"
echo ""
echo "   Required contents:"
echo "   DOMAIN=jwhitezaps.atoaz.com"
echo "   ACME_EMAIL=your-email@example.com"
echo "   POSTGRES_PASSWORD=not-used-in-prod"
echo "   DATABASE_URL=postgresql://user:pass@db-host:25060/dbname?sslmode=require"
echo "   GRAFANA_PASSWORD=your-secure-password"
echo "   TRAEFIK_DASHBOARD_AUTH=admin:\$apr1\$..."
echo ""
echo "5. Test Docker:"
echo "   docker run hello-world"
echo ""
echo "============================================="
