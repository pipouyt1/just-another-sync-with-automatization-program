plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
// la compilacion va fuera de OneDrive para que no sincronice miles de archivos
allprojects { layout.buildDirectory.set(file("C:/android-tools/build/" + project.name)) }
