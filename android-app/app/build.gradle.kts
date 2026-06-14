import java.util.Properties

// ─── Read the beginner-friendly config files ─────────────────────────────
// app.properties   → WEB_URL, APP_NAME, PACKAGE_ID   (the one file to edit)
// version.properties → VERSION_CODE, VERSION_NAME     (auto-managed by CI)
val appProps = Properties().apply {
    file("../app.properties").inputReader().use { load(it) }
}
val versionProps = Properties().apply {
    file("../version.properties").inputReader().use { load(it) }
}

val webUrl: String = appProps.getProperty("WEB_URL", "https://apkhub.example.com").trim()
val appName: String = appProps.getProperty("APP_NAME", "APKHub").trim()
val packageId: String = appProps.getProperty("PACKAGE_ID", "com.apkhub.app").trim()
val versionCode: Int = versionProps.getProperty("VERSION_CODE", "1").trim().toInt()
val versionName: String = versionProps.getProperty("VERSION_NAME", "1.0.0").trim()

// ─── Optional release signing ────────────────────────────────────────────
// If keystore.properties exists (local) or CI injects it, sign the release
// build properly. Otherwise the debug build is used (still installable).
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties()
if (keystorePropsFile.exists()) {
    keystoreProps.load(keystorePropsFile.inputReader())
}

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.apkhub.app"            // code package — fixed
    compileSdk = 34

    defaultConfig {
        applicationId = packageId            // app identity on the device — configurable
        minSdk = 21                          // Android 5.0+  (covers ~99% of devices)
        targetSdk = 34                       // Android 14
        this.versionCode = versionCode
        this.versionName = versionName

        // Expose config values to Kotlin code via BuildConfig
        buildConfigField("String", "WEB_URL", "\"$webUrl\"")
        buildConfigField("String", "APP_NAME", "\"$appName\"")

        // Inject the app name into string resources so the launcher label updates
        resValue("string", "app_name", appName)
    }

    signingConfigs {
        create("release") {
            if (keystorePropsFile.exists()) {
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false          // keep it simple; enable later for size optimisation
            isShrinkResources = false
            if (keystorePropsFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        debug {
            // debug builds are auto-signed by AGP with the debug key — always installable
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.0")
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("com.google.android.material:material:1.12.0")
}
