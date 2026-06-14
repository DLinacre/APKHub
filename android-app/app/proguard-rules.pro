# Default ProGuard / R8 rules. Minification is off by default (see build.gradle.kts).
# Enable it later by setting isMinifyEnabled = true and uncommenting the keep rules below.

# Keep WebView interface / JS bridge classes (none currently, but keep for future)
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# Keep BuildConfig
-keep class com.apkhub.app.BuildConfig { *; }
