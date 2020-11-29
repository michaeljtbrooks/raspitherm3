#!/bin/bash

echo "Installing Raspitherm!"

if [ "$EUID" -ne 0 ]
  then echo "Please run this installation as root"
  exit 1
fi

echo "  Installing prerequisites..."
sudo apt-get install -y build-essential unzip wget

echo "  Installing Python..."
sudo apt-get install -y python-dev python3-dev
sudo apt-get install -y python-setuptools python3-setuptools

echo "  Installing PyPi package management..."
sudo apt-get install -y python-pip python3-pip
sudo apt-get install -y python3-venv

echo "  Installing git repository manager..."
sudo apt-get install -y git

echo "  Installing PiGPIO (this may take a while on a Raspberry Pi)..."
cd /root
mkdir ~/Installers
cd ~/Installers
wget https://github.com/joan2937/pigpio/archive/master.zip
unzip master.zip
cd pigpio-master
make
sudo make install

echo "  Cloning Raspitherm (for Python3)..."
cd /opt
git clone https://github.com/michaeljtbrooks/raspitherm3.git /opt/raspitherm

echo "  Creating Python3 virtual environment for Raspitherm..."
python3 -m venv /opt/raspitherm/env
source /opt/raspitherm/env/bin/activate
pip3 install wheel
pip3 install -r /opt/raspitherm/src/requirements.txt
chmod -R 0755 /opt/raspitherm

echo "  Copying relevant startup scripts..."
cp /etc/rc.local /etc/rc.local-BACKUP
cp /opt/raspitherm/server_scripts/etc/rc.local /etc/rc.local

echo "  Starting Raspitherm server..."
sudo pigpiod
sudo /opt/raspitherm/env/bin/python /opt/raspitherm/src/raspitherm_listener.py

echo "Installation complete! Raspitherm is now running!"
exit 0
