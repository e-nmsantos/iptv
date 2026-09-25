plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
}

android {
    namespace = "pt.iptvplayer.tv"
    compileSdk = 36
    buildToolsVersion = "36.0.0"

    defaultConfig {
        applicationId = "pt.iptvplayer.tv"
        minSdk = 23
        targetSdk = 36
        versionCode = 18
        versionName = "0.13.0-beta01"

        // Optional TMDB metadata lookup. Supplied through -PTMDB_API_KEY=... or
        // gradle.properties so no API key is committed to the repository.
        buildConfigField(
            "String",
            "TMDB_API_KEY",
            "\"${project.findProperty("TMDB_API_KEY") ?: ""}\"",
        )

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    sourceSets {
        getByName("androidTest").assets.srcDir("$projectDir/schemas")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.06.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.tv:tv-material:1.1.0")
    // Lifecycle 2.11 requires compileSdk 37 and AGP 9.1; 2.10 is the newest
    // line compatible with this API 36 / AGP 8 project.
    //noinspection GradleDependency
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    //noinspection GradleDependency
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.room:room-runtime:2.8.4")
    implementation("androidx.room:room-ktx:2.8.4")
    ksp("androidx.room:room-compiler:2.8.4")
    androidTestImplementation("androidx.room:room-testing:2.8.4")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    implementation("androidx.media3:media3-exoplayer:1.11.0")
    implementation("androidx.media3:media3-exoplayer-hls:1.11.0")
    implementation("androidx.media3:media3-ui:1.11.0")
    implementation("com.google.zxing:core:3.5.4")
    implementation("org.json:json:20260719")
    // Coil 3.5 is built with Kotlin 2.4; keep 3.4 until the project compiler is upgraded.
    //noinspection NewerVersionAvailable
    implementation("io.coil-kt.coil3:coil-compose:3.4.0")
    //noinspection NewerVersionAvailable
    implementation("io.coil-kt.coil3:coil-network-okhttp:3.4.0")

    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
}
