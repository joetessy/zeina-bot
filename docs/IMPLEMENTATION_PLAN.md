# Zeina Evolution Plan
## From Terminal Assistant to GUI Agent with Tools

**Goal:** Transform Zeina into a fully-featured AI assistant with web search, tools, and a touch-friendly GUI for Raspberry Pi deployment.

**Target Hardware:** Raspberry Pi 4/5 with 5-7" touchscreen display

**Model:** llama3.1:8b (native tool calling support)

---

## Deployment Guide

### Raspberry Pi Setup
```bash
# Install system dependencies
sudo apt update
sudo apt install -y python3-pip portaudio19-dev

# Install Kivy dependencies
sudo apt install -y python3-setuptools git-core
sudo apt install -y libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

# Install Python packages
pip3 install -r requirements.txt

# Pull model
ollama pull llama3.1:8b

# Run GUI
python3 gui_main.py --fullscreen
```

### Autostart on Boot
```bash
# Add to ~/.config/autostart/zeina.desktop
[Desktop Entry]
Type=Application
Name=Zeina Assistant
Exec=/home/pi/Zeina/venv/bin/python3 /home/pi/Zeina/gui_main.py --fullscreen
```

---

## Next Steps

1. Final testing and deployment
