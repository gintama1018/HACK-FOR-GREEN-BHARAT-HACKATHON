[app]
title = InfraWatch Nexus
package.name = infrawatch
package.domain = org.infrawatch
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,json

version = 1.0.0

requirements = python3,hostpython3,android,fastapi,uvicorn,pathway,requests,google-generativeai,python-dotenv,aiofiles,python-multipart

orientation = portrait

osx.python_version = 3
osx.kivy_version = 2.2.1

fullscreen = 1

android.permissions = INTERNET,ACCESS_NETWORK_STATE,CAMERA,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION
android.api = 34
android.minapi = 24
android.archs = arm64-v8a,armeabi-v7a,x86,x86_64
android.allowBackup = True

android.accepts_src_and_apps_assets = True
android.enable_android_native_library_support = False
android.extract_from_assets = True
android.allow_replacing_external_files = False
android.disable_prototype_sdk = True
android.enable_initial_sdk_download = True

android.meta_data = org.infrawatch.nexus.MainActivity

android.assets = app/src/main/assets

android.copy_libs = 0

android.add_gradle_maven_repository = True

android.application子类 = android.app.Application

android.application_meta_data = org.infrawatch.nexus.MainActivity

android.ndk = 
android.ndk_api = 24

android.launcher_fill_icon_color = #10B981

android.studio.sdk_path = /home/mayank/android-sdk

android.allow_http = True

android.enable_cleartext = True
