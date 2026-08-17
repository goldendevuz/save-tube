#!/bin/bash
set -e

# ==========================================
# SaveTube Production Deployment Script
# ==========================================
echo "Starting deployment for SaveTube..."

# 1. Update system and install dependencies
echo "Updating packages and installing Docker/Git..."
sudo apt-get update
sudo apt-get install -y git curl docker.io
sudo systemctl enable --now docker

# Install Docker Compose (V2) if not present
if ! docker compose version > /dev/null 2>&1; then
    echo "Installing Docker Compose..."
    sudo mkdir -p /usr/local/lib/docker/cli-plugins
    sudo curl -SL https://github.com/docker/compose/releases/download/v2.24.5/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# 2. Clone repository if not exists
if [ ! -d "save-tube" ]; then
    echo "Cloning repository..."
    git clone https://github.com/goldendevuz/save-tube.git
else
    echo "Repository exists. Pulling latest changes..."
    cd save-tube
    git pull origin master
    cd ..
fi

cd save-tube

# 3. Create .env file if it doesn't exist
if [ ! -f "backend/.env" ]; then
    echo "Creating basic .env file..."
    echo "DEBUG=0" > backend/.env
    echo "SECRET_KEY=$(openssl rand -hex 32)" >> backend/.env
    echo "ALLOWED_HOSTS=*" >> backend/.env
fi

# 4. Build and start containers
echo "Starting Docker containers..."
sudo docker compose up -d --build

# 5. Apply migrations and load initial data
echo "Applying database migrations..."
sudo docker compose exec -T backend python manage.py migrate

# Check if users exist to avoid loading seed data on every deploy
USER_COUNT=$(sudo docker compose exec -T backend python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.count())")

if [ "$USER_COUNT" -eq "0" ]; then
    echo "Database is empty. Loading initial seed data..."
    sudo docker compose exec -T backend python manage.py loaddata seed.json
else
    echo "Database already contains data. Skipping seed.json."
fi

echo "=========================================="
echo "Deployment Complete! 🎉"
echo "Your application is running on port 8095."
echo "Access it via: http://<your-server-ip>:8095"
echo "=========================================="
