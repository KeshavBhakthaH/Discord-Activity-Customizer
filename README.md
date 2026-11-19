# Discord Activity Customizer 🎮✨

> A production-ready, ultra-lightweight Windows desktop application to customize your Discord Rich Presence activity locally via native IPC pipes — with **0% ban risk**, **zero bot/user token logins**, and **< 15 MB RAM usage**.

---

## 🌟 Features

- **Custom Titles & Details:** Change your game/app name, subdetails, and elapsed time dynamically.
- **In-App Logo Selection & Cropper:** Choose any image and use the built-in interactive cropper (Center Crop 1:1, Fit & Letterbox, Stretch) to produce perfect 512×512 PNGs.
- **Discord-Friendly Image CDN:** Direct, high-speed upload to `iili.io` (FreeImage.host) — eliminates 502 Bad Gateway / broken image placeholder icons caused by Discord proxy bot filters.
- **Ultra-Low Memory Footprint:**
  - **Open Foreground UI:** ~7.4 MB RAM
  - **Active RPC Streaming:** ~3.5 MB RAM
  - **Minimized in Tray:** ~2.2 MB RAM
- **Single-Instance Lock:** Native Win32 mutex and activation events prevent duplicate processes and duplicate tray icons. Launching again restores your existing session.
- **Windows Start Menu Search Integration:** Automatically installs a clean Windows shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs` so you can find the app instantly by typing its name (without `.exe`).
- **System Tray Background Mode:** Closing the window with **✕** minimizes to the system tray, keeping your custom activity live in the background.
- **Presets Manager:** Save, load, and manage your favorite presence profiles (e.g. Coding, Gaming, Music Production).
- **Dynamic Application ID Switcher:** Easily test or swap custom Discord Developer Application IDs directly within the UI.

---

## 🛡️ Safety & 100% Discord ToS Compliance

- **No Bot Tokens or User Credentials:** Never touches Discord passwords, user tokens, or Gateway WebSockets.
- **Direct Local IPC Pipe:** Communicates strictly with your locally running Discord desktop client via the official Discord IPC pipe (`\\?\pipe\discord-ipc-0`).
- **0% Ban Risk:** Completely indistinguishable from verified games and software (like Spotify, VS Code, or Steam games).

---

## 🚀 Quick Start

### 1. Download Standalone Executable (Recommended)
Download the latest `DiscordActivityCustomizer.exe` from the [GitHub Releases](https://github.com/KeshavBhakthaH/Discord-Activity-Customizer/releases) tab and run it directly. No installation or Python setup required!

### 2. Run from Source (Developers)

```powershell
# Clone the repository
git clone https://github.com/KeshavBhakthaH/Discord-Activity-Customizer.git
cd Discord-Activity-Customizer

# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py
```

### 3. Build Standalone EXE

Double-click `build_exe.bat` or run:
```powershell
python -m PyInstaller --noconfirm DiscordActivityCustomizer.spec
```
The compiled executable will be generated at `dist/DiscordActivityCustomizer.exe`.

---

## 📁 Project Structure

```
Discord-Activity-Customizer/
├── assets/
│   ├── app_icon.ico                 # Multi-size application icon
│   └── placeholder_logo.png         # Default 512x512 fallback logo
├── src/
│   ├── __init__.py
│   ├── constants.py                 # Styling colors, limits, Discord IDs, and paths
│   ├── image_service.py             # Validation, cropping, and high-reliability CDN upload
│   ├── memory_optimizer.py          # Native Win32 EmptyWorkingSet memory trimmer
│   ├── rpc_manager.py               # Thread-safe pypresence IPC wrapper
│   ├── single_instance.py           # Win32 Named Mutex & Show Event manager
│   ├── storage.py                   # Atomic JSON persistence (config, presets, cache)
│   ├── tray_manager.py              # Windows system tray integration
│   └── ui.py                        # CustomTkinter dark-mode GUI & live preview
├── build_exe.bat                    # One-click PyInstaller build script
├── create_start_shortcut.bat        # Windows Start Menu shortcut installer
├── DiscordActivityCustomizer.spec   # Optimized PyInstaller spec file
├── main.py                          # Application entry point
├── requirements.txt                 # Python dependencies
└── README.md
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
