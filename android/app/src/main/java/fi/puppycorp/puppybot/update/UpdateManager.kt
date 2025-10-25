package fi.puppycorp.puppybot.update

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import android.widget.Toast
import androidx.core.content.FileProvider
import fi.puppycorp.puppybot.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

object UpdateManager {
    private val httpClient by lazy { OkHttpClient() }

    private val universalApkPattern = Regex("""(?i).*(universal|arm64\+armeabi).*\\.apk$""")

    data class Release(val tag: String, val body: String?, val assets: List<Asset>)
    data class Asset(val name: String, val url: String, val size: Long)

    suspend fun checkAndPrompt(context: Context) {
        if (!BuildConfig.DEBUG) return

        val appContext = context.applicationContext
        val release = runCatching { fetchLatestRelease() }.getOrNull() ?: return
        val asset = release.assets.firstOrNull { universalApkPattern.matches(it.name) } ?: return
        val apkFile = download(appContext, asset.url, asset.name) ?: return

        val pinnedHex = BuildConfig.PINNED_RELEASE_CERT_SHA256
        if (pinnedHex.isBlank()) {
            apkFile.delete()
            showToast(appContext, "Missing release certificate pin.")
            return
        }

        if (!sameSigner(appContext, apkFile, pinnedHex)) {
            apkFile.delete()
            showToast(appContext, "Signature mismatch. Aborting.")
            return
        }

        if (!isUpgrade(appContext, apkFile)) {
            apkFile.delete()
            showToast(appContext, "No newer version found.")
            return
        }

        withContext(Dispatchers.Main) {
            promptInstall(appContext, apkFile)
        }
    }

    private suspend fun fetchLatestRelease(): Release? {
        val request = Request.Builder()
            .url("https://api.github.com/repos/${BuildConfig.GITHUB_RELEASE_OWNER}/${BuildConfig.GITHUB_RELEASE_REPO}/releases/latest")
            .header("Accept", "application/vnd.github+json")
            .build()

        httpClient.newCall(request).await().use { response ->
            if (!response.isSuccessful) return null
            val body = response.body?.string() ?: return null
            val json = JSONObject(body)
            val assets = json.optJSONArray("assets") ?: JSONArray()
            val assetList = buildList {
                for (i in 0 until assets.length()) {
                    val entry = assets.optJSONObject(i) ?: continue
                    add(
                        Asset(
                            name = entry.optString("name"),
                            url = entry.optString("browser_download_url"),
                            size = entry.optLong("size", -1L)
                        )
                    )
                }
            }
            return Release(
                tag = json.optString("tag_name"),
                body = json.optString("body", null),
                assets = assetList
            )
        }
    }

    private fun download(context: Context, url: String, filename: String): File? {
        val downloadsDir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: return null
        if (!downloadsDir.exists()) downloadsDir.mkdirs()
        val targetFile = File(downloadsDir, filename)
        if (targetFile.exists()) {
            targetFile.delete()
        }

        val request = Request.Builder().url(url).build()
        return try {
            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return null
                val body = response.body ?: return null
                body.byteStream().use { input ->
                    FileOutputStream(targetFile).use { output ->
                        input.copyTo(output)
                    }
                }
            }
            targetFile.takeIf { it.exists() && it.length() > 0L }
        } catch (ex: IOException) {
            targetFile.delete()
            null
        }
    }

    private fun certSha256(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return digest.joinToString(separator = "") { "%02x".format(it) }
    }

    private fun sameSigner(context: Context, apk: File, pinnedHex: String): Boolean {
        val apkInfo = context.packageManager.getPackageArchiveInfoCompat(
            apk.path,
            signatureFlags()
        ) ?: return false
        val signerBytes = apkInfo.firstSignerBytes() ?: return false
        val apkHash = certSha256(signerBytes)
        return apkHash.equals(pinnedHex, ignoreCase = true)
    }

    private fun isUpgrade(context: Context, apk: File): Boolean {
        val pm = context.packageManager
        val currentInfo = pm.getPackageInfoCompat(
            context.packageName,
            signatureFlags()
        )
        val newInfo = pm.getPackageArchiveInfoCompat(apk.path, 0) ?: return false
        if (newInfo.packageName != context.packageName) {
            return false
        }
        return newInfo.longVersionCode > currentInfo.longVersionCode
    }

    private fun promptInstall(context: Context, apk: File) {
        if (!context.packageManager.canRequestPackageInstalls()) {
            val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                .setData(Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            return
        }

        val uri = FileProvider.getUriForFile(context, "${context.packageName}.provider", apk)
        val intent = Intent(Intent.ACTION_INSTALL_PACKAGE).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            putExtra(Intent.EXTRA_RETURN_RESULT, true)
        }
        context.startActivity(intent)
    }

    private suspend fun showToast(context: Context, message: String) {
        withContext(Dispatchers.Main) {
            Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
        }
    }
}

private fun PackageManager.getPackageArchiveInfoCompat(path: String, flags: Int): PackageInfo? {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        getPackageArchiveInfo(path, PackageManager.PackageInfoFlags.of(flags.toLong()))
    } else {
        @Suppress("DEPRECATION")
        getPackageArchiveInfo(path, flags)
    }
}

private fun PackageManager.getPackageInfoCompat(packageName: String, flags: Int): PackageInfo {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        getPackageInfo(packageName, PackageManager.PackageInfoFlags.of(flags.toLong()))
    } else {
        @Suppress("DEPRECATION")
        getPackageInfo(packageName, flags)
    }
}

private fun signatureFlags(): Int {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        PackageManager.GET_SIGNING_CERTIFICATES
    } else {
        @Suppress("DEPRECATION")
        PackageManager.GET_SIGNATURES
    }
}

private fun PackageInfo.firstSignerBytes(): ByteArray? {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        signingInfo?.apkContentsSigners?.firstOrNull()?.toByteArray()
    } else {
        @Suppress("DEPRECATION")
        signatures?.firstOrNull()?.toByteArray()
    }
}

suspend fun Call.await(): Response = suspendCancellableCoroutine { continuation ->
    enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) {
            if (continuation.isCancelled) return
            continuation.resumeWithException(e)
        }

        override fun onResponse(call: Call, response: Response) {
            continuation.resume(response)
        }
    })

    continuation.invokeOnCancellation {
        try {
            cancel()
        } catch (_: Throwable) {
        }
    }
}
