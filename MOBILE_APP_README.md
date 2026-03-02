# InfraWatch Nexus Mobile App

A mobile WebView wrapper for the InfraWatch Nexus civic intelligence platform.

## Quick Start

### Option 1: Pre-built APK (Recommended)
Install the APK directly on your Android device:
```
infrawatch-nexus.apk
```

### Option 2: Connect to Local Server
1. Start the server on your machine:
   ```bash
   cd HACK-FOR-GREEN-BHARAT-HACKATHON
   bash start.sh
   ```

2. Make sure your phone is on the same WiFi network as your computer

3. Find your computer's local IP address:
   - Linux/Mac: `hostname -I | awk '{print $1}'`
   - Windows: `ipconfig`

4. The app connects to `http://10.0.2.2:8000/` (Android emulator localhost)
   - For physical devices, modify `MainActivity.java` to use your computer's IP

## Features

- **Full WebView** - Replicates the web app experience exactly
- **Camera Access** - Supports photo upload for reporting
- **Offline Ready** - Works when connected to the server
- **Progress Bar** - Shows loading status

## Building from Source

### Prerequisites
- Java JDK 17+
- Android SDK (API 34)
- Gradle 8.2+

### Build
```bash
cd android_app
export ANDROID_HOME=~/android-sdk
./gradlew assembleDebug
```

The APK will be at: `app/build/outputs/apk/debug/app-debug.apk`

## Usage

1. Launch the app
2. The app will connect to `http://10.0.2.2:8000/` (localhost for emulator)
3. For physical device: edit MainActivity.java to use your server's IP

### Changing Server URL

Edit `app/src/main/java/org/infrawatch/nexus/MainActivity.java`:
```java
String serverUrl = "http://YOUR_SERVER_IP:8000/";
```

## Architecture

```
┌─────────────────────────────┐
│    Android WebView App     │
├─────────────────────────────┤
│  MainActivity.java         │
│  - Fullscreen WebView      │
│  - Progress bar            │
│  - File upload support     │
│  - Camera access           │
└─────────────────────────────┘
            │
            ▼ (connects to)
┌─────────────────────────────┐
│   FastAPI + Pathway        │
│   (your existing server)  │
└─────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `android_app/app/src/main/java/.../MainActivity.java` | Main WebView activity |
| `android_app/app/src/main/AndroidManifest.xml` | App permissions |
| `android_app/app/build.gradle` | Build configuration |
| `infrawatch-nexus.apk` | Pre-built debug APK |

## License

Same as main project - Hackathon project.
