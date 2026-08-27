# Socket.IO
-keep class io.socket.** { *; }
-keepclassmembers class io.socket.** { *; }

# Gson
-keepattributes Signature
-keepattributes *Annotation*
-keep class com.google.gson.** { *; }
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer

# CEPRESA models
-keep class com.example.cepresaandroid.** { *; }
