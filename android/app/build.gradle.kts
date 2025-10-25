plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

val githubReleaseOwner = providers.gradleProperty("githubReleaseOwner").orElse("puppycorp")
val githubReleaseRepo = providers.gradleProperty("githubReleaseRepo").orElse("puppybot")
val pinnedReleaseCertSha256 = providers.gradleProperty("pinnedReleaseCertSha256").orElse("REPLACE_WITH_CERT_SHA256")

android {
    namespace = "fi.puppycorp.puppybot"
    compileSdk = 36

    defaultConfig {
        applicationId = "fi.puppycorp.puppybot"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField("String", "GITHUB_RELEASE_OWNER", "\"${githubReleaseOwner.get()}\"")
        buildConfigField("String", "GITHUB_RELEASE_REPO", "\"${githubReleaseRepo.get()}\"")
        buildConfigField("String", "PINNED_RELEASE_CERT_SHA256", "\"${pinnedReleaseCertSha256.get()}\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            setProperty("archivesBaseName", "puppybot")
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
        buildConfig = true
    }
}

dependencies {

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.coroutines.android)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}
