import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm") version "2.4.21"
    kotlin("plugin.serialization") version "2.4.21"
    id("org.jetbrains.kotlinx.kover") version "0.9.11"
    id("org.jetbrains.dokka-javadoc") version "2.2.0"
    `maven-publish`
    signing
}

group = "ai.vaquill"
version = "0.1.0"
description = "Kotlin SDK for the Vaquill US Data API"

repositories {
    mavenCentral()
}

dependencies {
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    api("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.11.0")

    testImplementation(platform("org.junit:junit-bom:5.14.4"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testImplementation(kotlin("test"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

java {
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
    withSourcesJar()
    withJavadocJar()
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_11)
        // Compile against the JDK 11 API surface even when building on a newer JDK.
        freeCompilerArgs.addAll("-Xjdk-release=11")
        allWarningsAsErrors.set(true)
    }
}

// The Java `javadoc` task has no sources in a Kotlin project, so the javadoc jar that Maven Central
// requires is filled with Dokka's Javadoc-format HTML instead.
tasks.named<Jar>("javadocJar") {
    dependsOn(tasks.named("dokkaGeneratePublicationJavadoc"))
    from(layout.buildDirectory.dir("dokka/javadoc"))
}

// Byte-for-byte reproducible archives: the jars attached to the GitHub Release are built by a different
// job than the ones signed and uploaded to Maven Central, and must be identical.
tasks.withType<AbstractArchiveTask>().configureEach {
    isPreserveFileTimestamps = false
    isReproducibleFileOrder = true
}

tasks.withType<JavaCompile>().configureEach { options.release.set(11) }

val specPath = rootDir.parentFile.resolve("openapi/vaquill-us.json").path

tasks.test {
    useJUnitPlatform { excludeTags("live") }
    systemProperty("vaquill.spec", specPath)
    systemProperty("vaquill.root", rootDir.path)
    testLogging { events("failed", "skipped") }
}

// Live smoke: spends at most a few credits on the real API. Never part of `build` or `check`.
//   VAQUILL_API_KEY=... ./gradlew liveSmoke -PliveSmoke
val liveSmoke by tasks.registering(Test::class) {
    group = "verification"
    description = "Tiny, credit-capped smoke test against the production API (requires -PliveSmoke)."
    testClassesDirs = sourceSets.test.get().output.classesDirs
    classpath = sourceSets.test.get().runtimeClasspath
    useJUnitPlatform { includeTags("live") }
    onlyIf { providers.gradleProperty("liveSmoke").isPresent }
    testLogging { events("passed", "failed", "skipped") }
}

kover {
    reports {
        filters {
            excludes {
                // Generated data classes: exercised by the schema round-trip test, not line-counted.
                packages("ai.vaquill.sdk.models")
            }
        }
        verify {
            rule { minBound(85) }
        }
    }
}

publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["java"])
            artifactId = "vaquill-kotlin"
            pom {
                name.set("Vaquill Kotlin SDK")
                description.set("Kotlin SDK (coroutines, Flow, kotlinx.serialization) for the Vaquill US Data API.")
                url.set("https://www.vaquill.ai")
                licenses {
                    license {
                        name.set("MIT License")
                        url.set("https://opensource.org/licenses/MIT")
                    }
                }
                developers {
                    developer {
                        id.set("vaquill")
                        name.set("Vaquill")
                        organization.set("Vaquill")
                        organizationUrl.set("https://www.vaquill.ai")
                        url.set("https://www.vaquill.ai")
                    }
                }
                scm {
                    url.set("https://github.com/vaquill-ai/vaquill-sdks")
                    connection.set("scm:git:https://github.com/vaquill-ai/vaquill-sdks.git")
                    developerConnection.set("scm:git:ssh://git@github.com/vaquill-ai/vaquill-sdks.git")
                }
                issueManagement {
                    system.set("GitHub")
                    url.set("https://github.com/vaquill-ai/vaquill-sdks/issues")
                }
            }
        }
    }
    // Credentials come only from the caller's Gradle properties. None are stored here.
    val centralUser = providers.gradleProperty("centralUsername")
    val centralPass = providers.gradleProperty("centralPassword")
    if (centralUser.isPresent && centralPass.isPresent) {
        repositories {
            maven {
                name = "central"
                url = uri("https://ossrh-staging-api.central.sonatype.com/service/local/staging/deploy/maven2/")
                credentials {
                    username = centralUser.get()
                    password = centralPass.get()
                }
            }
        }
    }
}

// Signing runs only when an in-memory key is supplied, so local builds and publishToMavenLocal need no
// GPG setup. CI passes it as ORG_GRADLE_PROJECT_signingInMemoryKey and
// ORG_GRADLE_PROJECT_signingInMemoryKeyPassword (Gradle maps those environment variables to project
// properties). A key without its password, or the reverse, fails the build instead of publishing unsigned.
val signingKey = providers.gradleProperty("signingInMemoryKey")
val signingKeyPassword = providers.gradleProperty("signingInMemoryKeyPassword")
if (signingKey.isPresent) {
    signing {
        useInMemoryPgpKeys(signingKey.get(), signingKeyPassword.get())
        sign(publishing.publications["maven"])
    }
}
