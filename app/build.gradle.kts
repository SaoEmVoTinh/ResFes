import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.chaquopy)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

val keystoreProperties = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) {
        file.inputStream().use { load(it) }
    }
}

fun firstNonBlank(vararg values: String?): String? =
    values.firstOrNull { !it.isNullOrBlank() }?.trim()

val releaseStorePath = firstNonBlank(
    keystoreProperties.getProperty("storeFile"),
    System.getenv("RESFES_RELEASE_STORE_FILE")
)
val releaseStorePassword = firstNonBlank(
    keystoreProperties.getProperty("storePassword"),
    System.getenv("RESFES_RELEASE_STORE_PASSWORD")
)
val releaseKeyAlias = firstNonBlank(
    keystoreProperties.getProperty("keyAlias"),
    System.getenv("RESFES_RELEASE_KEY_ALIAS")
)
val releaseKeyPassword = firstNonBlank(
    keystoreProperties.getProperty("keyPassword"),
    System.getenv("RESFES_RELEASE_KEY_PASSWORD")
)

val hasReleaseSigning = listOf(
    releaseStorePath,
    releaseStorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
).all { !it.isNullOrBlank() }

val releaseStoreFile = releaseStorePath?.let {
    val moduleResolved = file(it)
    val rootResolved = rootProject.file(it)
    when {
        moduleResolved.exists() -> moduleResolved
        rootResolved.exists() -> rootResolved
        moduleResolved.isAbsolute -> moduleResolved
        else -> rootResolved
    }
}

val releaseTaskRequested = gradle.startParameter.taskNames.any { task ->
    val t = task.lowercase()
    t.contains("release") || t.contains("bundle") || t.contains("publish")
}

android {
    namespace = "com.ar.dalap"
    compileSdk = 34 // Sửa lại cho đúng version, không cần release block ở đây

    defaultConfig {
        applicationId = "com.ar.dalap"
        minSdk = 24
        targetSdk = 34 // Sửa lại cho đúng version
        versionCode = 1
        versionName = "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            abiFilters += listOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")
        }
    }

    signingConfigs {
        create("release") {
            if (hasReleaseSigning) {
                storeFile = releaseStoreFile
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
    }
}

if (releaseTaskRequested) {
    if (!hasReleaseSigning) {
        throw GradleException(
            "Missing release signing config. Provide keystore.properties at project root or set env vars: " +
                "RESFES_RELEASE_STORE_FILE, RESFES_RELEASE_STORE_PASSWORD, RESFES_RELEASE_KEY_ALIAS, RESFES_RELEASE_KEY_PASSWORD"
        )
    }
    if (releaseStoreFile == null || !releaseStoreFile.exists()) {
        throw GradleException("Release keystore not found: ${releaseStoreFile?.absolutePath ?: "<empty>"}")
    }
}

chaquopy {
    defaultConfig {
        // Match build machine Python major.minor to avoid .pyc incompatibility warnings.
        version = "3.10"
        pyc {
            src = false
            pip = false
            stdlib = false
        }
        pip {
            install("flask")
            install("flask-cors")
            install("groq==0.4.2")
            install("httpx==0.27.2")
            install("pydantic<2.0.0")
            install("python-dotenv")
            install("requests")
            install("pyOpenSSL==24.1.0")
            install("cryptography==42.0.8")
            install("PyPDF2")
            install("python-docx")
            install("openpyxl")
            install("python-pptx")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir("src/main/python")
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    // KHÔNG thêm version thủ công cho material3 hoặc các thư viện compose khác
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}
