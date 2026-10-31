-keep class androidx.media3.** { *; }
-dontwarn androidx.media3.**

# NextLib FFmpeg decoders: the native code calls back into these classes by name.
-keep class io.github.anilbeesetti.nextlib.** { *; }
-dontwarn io.github.anilbeesetti.nextlib.**
