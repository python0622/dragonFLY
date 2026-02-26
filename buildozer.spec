[app]

# 应用名称
title = 设备监控系统

# 包名
package.name = devicecounter

# 包域名（反向域名）
package.domain = org.example

# 应用版本
version = 1.0.0

# 应用入口文件
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt,json

# 应用需求
requirements = python3,kivy==2.2.1,plyer==2.1,pyjnius==1.5.0,android

# 应用图标
icon.filename = %(source.dir)s/icon.png

# 应用权限
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# Android API级别
android.api = 31
android.minapi = 21
android.ndk = 23b
android.sdk = 31

# 架构
android.arch = arm64-v8a

# 存储路径
android.entrypoint = org.kivy.android.PythonActivity
android.app_lib_dir = %(source.dir)s/libs

# 是否使用Java/Cython编译
android.add_src =

# 是否启用Gradle构建
android.gradle = 1

# 是否启用AndroidX
android.use_androidx = 1

# 是否启用广告
android.enable_ads = 0

# 是否启用Google Play服务
android.google_play_services = 0

# 是否启用自动备份
android.allow_backup = 1

# 应用主题
android.theme = @android:style/Theme.NoTitleBar

# 应用方向
android.orientation = landscape

# 是否全屏
android.fullscreen = 0

# 启动时是否显示日志
android.log_level = 2

# 窗口大小（开发时）
window.size = 1200x800

# 是否为命令行应用
osx.python_version = 3
osx.kivy_version = 2.2.1

[buildozer]
log_level = 2
warn_on_root = 1

[requirements]
# 已在上面的requirements中定义
