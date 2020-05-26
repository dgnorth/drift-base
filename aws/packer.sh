#!/bin/sh
set -e


sudo apt -y update
sudo apt -y upgrade
sudo apt -y install docker.io

sudo mv /tmp/driftapp.service /etc/systemd/system/
sudo mkdir /etc/driftapp
sudo mv /tmp/docker-compose.yml /etc/driftapp/

sudo curl -L "https://github.com/docker/compose/releases/download/1.25.5/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

sudo systemctl enable driftapp
